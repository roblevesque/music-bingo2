"""Host console: start the game, play songs, run rounds, check tickets.

Like play.py, mutating handlers are `async def` with no `await` in their critical
section, so they execute one at a time on the event loop.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_user
from app.models import Game, GameSong, Round, Song, Ticket, User
from app.routes.games import owned_game, parse_rules
from app.routes.play import join_url
from app.security import check_csrf
from app.services.checker import verify_claim
from app.services.events import HOST, Event, stream
from app.services.patterns import MODE_LINES, describe_line
from app.services.playlist import PlaylistExhausted, advance, new_play_order, played_ids, reshuffle_remaining, skip_next
from app.services.snapshots import broadcast, host_state, round_name
from app.web import render

router = APIRouter(prefix="/games/{game_id}/run")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _state(request: Request, session: Session, game: Game) -> dict:
    return host_state(session, game, join_url(request, game))


def _commit_and_broadcast(request: Request, session: Session, game: Game) -> dict:
    session.add(game)
    session.commit()
    broadcast(request.app.state.hub, session, game, join_url(request, game))
    return _state(request, session, game)


def _require_active(game: Game) -> None:
    if game.status == "draft":
        raise _conflict("Start the game first.")
    if game.status == "finished":
        raise _conflict("This game has finished.")


@router.get("")
def console(request: Request, game_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    game = owned_game(session, user, game_id)
    return render(request, "console.html", user=user, game=game, state=_state(request, session, game))


@router.get("/state")
def state(request: Request, game_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    return _state(request, session, owned_game(session, user, game_id))


@router.get("/events")
async def events(request: Request, game_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    game = owned_game(session, user, game_id)
    hub = request.app.state.hub
    subscription = hub.subscribe(game.id, HOST)
    initial = [Event("state", _state(request, session, game))]

    async def body():
        try:
            async for chunk in stream(subscription, initial):
                yield chunk
        finally:
            hub.unsubscribe(subscription)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- actions


@router.post("/start")
async def start(request: Request, game_id: int, csrf_token: str = Form(""),
                user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if game.status != "draft":
        raise _conflict("This game has already started.")
    pool = session.exec(select(GameSong.song_id).where(GameSong.game_id == game.id)).all()
    game.play_order = new_play_order(list(pool))
    game.current_index = 0
    game.current_round = 1
    game.status = "active"
    return _commit_and_broadcast(request, session, game)


@router.post("/next")
async def next_song(request: Request, game_id: int, csrf_token: str = Form(""),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    try:
        _song_id, game.current_index = advance(list(game.play_order), game.current_index)
    except PlaylistExhausted:
        raise _conflict("Every song has been played.") from None
    return _commit_and_broadcast(request, session, game)


@router.post("/skip")
async def skip(request: Request, game_id: int, csrf_token: str = Form(""),
               user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    try:
        game.play_order = skip_next(list(game.play_order), game.current_index)
    except ValueError as exc:
        raise _conflict(str(exc)) from None
    return _commit_and_broadcast(request, session, game)


@router.post("/reshuffle")
async def reshuffle(request: Request, game_id: int, csrf_token: str = Form(""),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    game.play_order = reshuffle_remaining(list(game.play_order), game.current_index)
    return _commit_and_broadcast(request, session, game)


@router.post("/finish")
async def finish(request: Request, game_id: int, csrf_token: str = Form(""),
                 user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    game.status = "finished"
    return _commit_and_broadcast(request, session, game)


@router.post("/round")
async def select_round(request: Request, game_id: int, number: int = Form(...), csrf_token: str = Form(""),
                       user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Make another round current (normally the next one)."""
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    exists = session.exec(select(Round.id).where(Round.game_id == game.id, Round.number == number)).first()
    if exists is None:
        raise _conflict("There is no round with that number. Add one first.")
    game.current_round = number
    return _commit_and_broadcast(request, session, game)


@router.post("/rules")
async def update_rules(request: Request, game_id: int, round_id: int = Form(...), name: str = Form(""),
                       mode: str = Form(MODE_LINES), lines_required: str = Form("1"), rows: bool = Form(False),
                       columns: bool = Form(False), diagonals: bool = Form(False), csrf_token: str = Form(""),
                       user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Change what counts as a win. Allowed at any time, including mid-game."""
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    target = session.get(Round, round_id)
    if target is None or target.game_id != game.id:
        raise HTTPException(status_code=404, detail="Round not found")
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals)
    if errors:
        raise _conflict(errors[0])
    target.name = (name.strip() or f"Round {target.number}")[:60]
    target.mode, target.lines_required = rules.mode, rules.lines_required
    target.rows, target.columns, target.diagonals = rules.rows, rules.columns, rules.diagonals
    session.add(target)
    return _commit_and_broadcast(request, session, game)


@router.post("/rounds")
async def add_round(request: Request, game_id: int, name: str = Form(""), mode: str = Form(MODE_LINES),
                    lines_required: str = Form("1"), rows: bool = Form(False), columns: bool = Form(False),
                    diagonals: bool = Form(False), csrf_token: str = Form(""),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals)
    if errors:
        raise _conflict(errors[0])
    numbers = session.exec(select(Round.number).where(Round.game_id == game.id)).all()
    number = max(numbers, default=0) + 1
    session.add(Round(
        game_id=game.id, number=number, name=(name.strip() or f"Round {number}")[:60], mode=rules.mode,
        lines_required=rules.lines_required, rows=rules.rows, columns=rules.columns, diagonals=rules.diagonals,
    ))
    return _commit_and_broadcast(request, session, game)


@router.post("/check")
async def check_ticket(request: Request, game_id: int, ticket_number: int = Form(...), csrf_token: str = Form(""),
                       user: User = Depends(require_user), session: Session = Depends(get_session)):
    """For printed tickets: would this ticket win the current round, right now?"""
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    _require_active(game)
    ticket = session.exec(select(Ticket).where(Ticket.game_id == game.id, Ticket.number == ticket_number)).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"There is no ticket number {ticket_number} in this game.")
    current = session.exec(select(Round).where(Round.game_id == game.id, Round.number == game.current_round)).first()
    if current is None:
        raise _conflict("There is no round in progress.")
    try:
        result = verify_claim(ticket.cells, played_ids(game.play_order, game.current_index), game.grid_size, current.rules())
    except ValueError as exc:
        raise _conflict(str(exc)) from None
    titles = {s.id: s.title for s in session.exec(select(Song).where(Song.id.in_(result.missing_song_ids))).all()} if result.missing_song_ids else {}
    return {
        "ticket": ticket.number,
        "round": round_name(current),
        "status": result.status,
        "lines": [describe_line(line) for line in result.completed],
        "squares_needed": result.squares_needed,
        "missing": [titles.get(sid, "?") for sid in result.missing_song_ids],
    }
