"""Player side: join a game with a code and team name, mark a ticket, claim bingo.

State-changing handlers here are `async def` with no `await` between reading and
writing the game. On one event loop that makes them run one at a time, so two
claims or two "next song" clicks can never interleave. That is why the app runs a
single worker (see README).
"""

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import get_session
from app.models import Claim, Game, Round, Song, Team, Ticket
from app.security import check_csrf
from app.services.brand_store import brand_context
from app.services.checker import WIN, verify_claim
from app.services.events import PLAYERS, Event, stream
from app.services.patterns import describe_line
from app.services.playlist import played_ids
from app.services.snapshots import broadcast, public_state, round_name
from app.web import render

router = APIRouter()

CLAIM_COOLDOWN_SECONDS = 5  # after a rejected claim, so the host isn't spammed
MIN_TEAM_NAME, MAX_TEAM_NAME = 2, 30


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def game_by_code(session: Session, raw_code: str) -> Game | None:
    return session.exec(select(Game).where(Game.code == normalize_code(raw_code))).first()


def team_for(request: Request, session: Session, game: Game) -> Team | None:
    """Which team (if any) this browser joined for this game. The cookie is signed."""
    team_id = (request.session.get("teams") or {}).get(str(game.id))
    team = session.get(Team, team_id) if team_id else None
    return team if team is not None and team.game_id == game.id else None


def join_url(request: Request, game: Game) -> str:
    base = request.app.state.settings.public_url or str(request.base_url).rstrip("/")
    return f"{base}/join/{game.code}"


def age_seconds(moment: datetime) -> float:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - moment.replace(tzinfo=None)).total_seconds()


# ---------------------------------------------------------------- joining


def _join_page(request: Request, *, status_code: int = 200, code: str = "", team_name: str = "", errors=()):
    return render(request, "join.html", status_code=status_code, code=code, team_name=team_name, errors=list(errors))


@router.get("/join")
def join_form(request: Request, code: str = ""):
    return _join_page(request, code=normalize_code(code))


@router.get("/join/{code}")
def join_form_for_code(request: Request, code: str, session: Session = Depends(get_session)):
    game = game_by_code(session, code)
    if game is None:
        return _join_page(request, status_code=404, code=normalize_code(code),
                          errors=["No game found with that code. Check it and try again."])
    if team_for(request, session, game):
        return _redirect(f"/play/{game.code}")
    return _join_page(request, code=game.code)


def _create_team(session: Session, game: Game, name: str) -> Team | str:
    """Returns the new Team, or a message explaining why the team couldn't join."""
    key = name.casefold()
    for _ in range(5):
        if session.exec(select(Team.id).where(Team.game_id == game.id, Team.name_key == key)).first() is not None:
            return "That team name is already taken. Please choose another."
        taken = select(Team.ticket_id).where(Team.game_id == game.id)
        free = session.exec(select(Ticket.id).where(Ticket.game_id == game.id, Ticket.id.not_in(taken))).all()
        if not free:
            return "Every ticket in this game has been taken."
        team = Team(game_id=game.id, ticket_id=random.choice(free), name=name, name_key=key)
        session.add(team)
        try:
            session.commit()
            return team
        except IntegrityError:  # lost a race for the name or the ticket: look again
            session.rollback()
    return "Could not join right now. Please try again."


@router.post("/join")
async def join_submit(
    request: Request,
    code: str = Form(""),
    team_name: str = Form(""),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = game_by_code(session, code)
    if game is None:
        return _join_page(request, status_code=404, code=normalize_code(code), team_name=team_name,
                          errors=["No game found with that code. Check it and try again."])
    if team_for(request, session, game):  # this browser already joined: just resume
        return _redirect(f"/play/{game.code}")
    name = " ".join(team_name.split())
    errors = []
    if not MIN_TEAM_NAME <= len(name) <= MAX_TEAM_NAME:
        errors.append(f"Team name must be {MIN_TEAM_NAME}-{MAX_TEAM_NAME} characters.")
    if game.status == "finished":
        errors.append("This game has finished.")
    result = _create_team(session, game, name) if not errors else None
    if isinstance(result, str):
        errors.append(result)
    if errors:
        return _join_page(request, status_code=400, code=game.code, team_name=name, errors=errors)
    teams = dict(request.session.get("teams") or {})
    teams[str(game.id)] = result.id
    request.session["teams"] = teams
    broadcast(request.app.state.hub, session, game, join_url(request, game))
    return _redirect(f"/play/{game.code}")


# ---------------------------------------------------------------- playing


def _require_team(request: Request, session: Session, code: str) -> tuple[Game, Team]:
    game = game_by_code(session, code)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    team = team_for(request, session, game)
    if team is None:
        raise HTTPException(status_code=403, detail="Join this game first")
    return game, team


@router.get("/play/{code}")
def play_page(request: Request, code: str, session: Session = Depends(get_session)):
    game = game_by_code(session, code)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    team = team_for(request, session, game)
    if team is None:
        return _redirect(f"/join/{game.code}")
    ticket = session.get(Ticket, team.ticket_id)
    songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(ticket.cells))).all()}
    marks = set(team.marks)
    cells = []
    for position, song_id in enumerate(ticket.cells):
        song = songs.get(song_id)
        cells.append({
            "pos": position,
            "title": song.title if song else "(song removed)",
            "artist": song.artist if song else "",
            "marked": position in marks,
        })
    return render(request, "play.html", game=game, team=team, ticket=ticket, cells=cells,
                  size=game.grid_size, state=public_state(session, game),
                  brand=brand_context(session, request.app.state.settings, game.owner_id, game.code))


@router.post("/play/{code}/mark")
async def mark(
    request: Request,
    code: str,
    position: int = Form(...),
    marked: bool = Form(False),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game, team = _require_team(request, session, code)
    if not 0 <= position < game.grid_size ** 2:
        raise HTTPException(status_code=400, detail="No such square")
    marks = set(team.marks)
    marks.add(position) if marked else marks.discard(position)
    team.marks = sorted(marks)  # assign a new list so the change is saved
    session.add(team)
    session.commit()
    return {"ok": True}


def _claim_reply(status: str, message: str, http_status: int = 200) -> JSONResponse:
    return JSONResponse({"status": status, "message": message}, status_code=http_status)


@router.post("/play/{code}/claim")
async def claim(
    request: Request,
    code: str,
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game, team = _require_team(request, session, code)
    if game.status != "active":
        return _claim_reply("unavailable", "The game isn't running right now.", 409)
    current = session.exec(select(Round).where(Round.game_id == game.id, Round.number == game.current_round)).first()
    if current is None:
        return _claim_reply("unavailable", "There is no round in progress.", 409)

    already_won = session.exec(
        select(Claim.id).where(Claim.team_id == team.id, Claim.round_number == current.number, Claim.status == WIN)
    ).first()
    if already_won is not None:
        return _claim_reply("already_claimed", "Your team has already won this round.")
    last_rejected = session.exec(
        select(Claim).where(Claim.team_id == team.id, Claim.status == "rejected").order_by(Claim.id.desc()).limit(1)
    ).first()
    if last_rejected is not None and age_seconds(last_rejected.created_at) < CLAIM_COOLDOWN_SECONDS:
        return _claim_reply("cooldown", "Hold on a few seconds before calling again.", 429)

    ticket = session.get(Ticket, team.ticket_id)
    try:
        result = verify_claim(ticket.cells, played_ids(game.play_order, game.current_index), game.grid_size, current.rules())
    except ValueError:
        return _claim_reply("unavailable", "This round's rules need fixing by the host.", 409)

    if result.is_win:
        detail = ", ".join(describe_line(line) for line in result.completed) or "full house"
    else:
        detail = f"{result.squares_needed} song{'' if result.squares_needed == 1 else 's'} short"
    session.add(Claim(
        game_id=game.id, team_id=team.id, round_number=current.number, round_name=round_name(current),
        status=result.status, songs_played=game.current_index, detail=detail,
    ))
    session.commit()
    broadcast(request.app.state.hub, session, game, join_url(request, game))
    if result.is_win:
        return _claim_reply(WIN, "Bingo! Your card checks out. Wait for the host to confirm.")
    return _claim_reply("rejected", "Not a winning card yet. Keep listening!")


@router.get("/play/{code}/events")
async def player_events(request: Request, code: str, session: Session = Depends(get_session)):
    game, _team = _require_team(request, session, code)
    hub = request.app.state.hub
    subscription = hub.subscribe(game.id, PLAYERS)  # subscribe first so no update is missed
    initial = [Event("state", public_state(session, game))]

    async def body():
        try:
            async for chunk in stream(subscription, initial):
                yield chunk
        finally:
            hub.unsubscribe(subscription)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
