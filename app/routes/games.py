"""Games: create from a song pool, generate tickets, manage rounds, view tickets."""

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_user
from app.models import Claim, Game, GameSong, Round, Song, Team, Ticket, User
from app.security import check_csrf
from app.services.patterns import MODE_FULL_HOUSE, MODE_LINES, RoundRules, describe_rules, validate_rules
from app.services.ticket_gen import TicketGenerationError, generate_tickets
from app.web import flash, render

router = APIRouter(prefix="/games")

DEFAULT_GRID = 5
MIN_GRID, MAX_GRID = 3, 9
DEFAULT_TICKETS = 30
MAX_TICKETS = 500
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to avoid mix-ups when typing


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def owned_game(session: Session, user: User, game_id: int) -> Game:
    game = session.get(Game, game_id)
    if game is None or game.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _new_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if session.exec(select(Game.id).where(Game.code == code)).first() is None:
            return code
    raise RuntimeError("could not allocate a unique game code")


def _library(session: Session, user: User) -> list[Song]:
    return session.exec(select(Song).where(Song.owner_id == user.id).order_by(func.lower(Song.title), Song.id)).all()


# ---------------------------------------------------------------- list / create


@router.get("")
def games_list(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    games = session.exec(select(Game).where(Game.owner_id == user.id).order_by(Game.created_at.desc())).all()
    ids = [game.id for game in games]
    tickets = dict(
        session.exec(
            select(Ticket.game_id, func.count(Ticket.id)).where(Ticket.game_id.in_(ids)).group_by(Ticket.game_id)
        ).all()
    )
    songs = dict(
        session.exec(
            select(GameSong.game_id, func.count(GameSong.song_id))
            .where(GameSong.game_id.in_(ids))
            .group_by(GameSong.game_id)
        ).all()
    )
    return render(request, "games.html", user=user, games=games, ticket_counts=tickets, song_counts=songs)


def _new_game_page(request, user, session, *, status_code=200, form=None, selected=(), errors=()):
    form = form or {"name": "", "grid_size": str(DEFAULT_GRID), "ticket_count": str(DEFAULT_TICKETS)}
    return render(
        request,
        "new_game.html",
        status_code=status_code,
        user=user,
        songs=_library(session, user),
        form=form,
        selected=set(selected),
        errors=list(errors),
        min_grid=MIN_GRID,
        max_grid=MAX_GRID,
        max_tickets=MAX_TICKETS,
    )


@router.get("/new")
def new_game_form(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    return _new_game_page(request, user, session)


@router.post("/new")
async def new_game_submit(
    request: Request,
    name: str = Form(""),
    grid_size: str = Form(str(DEFAULT_GRID)),
    ticket_count: str = Form(str(DEFAULT_TICKETS)),
    song_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    name = name.strip()
    form = {"name": name, "grid_size": grid_size, "ticket_count": ticket_count}
    errors: list[str] = []
    if not 1 <= len(name) <= 100:
        errors.append("Give the game a name (up to 100 characters).")
    try:
        size = int(grid_size)
        if not MIN_GRID <= size <= MAX_GRID:
            raise ValueError
    except ValueError:
        size = DEFAULT_GRID
        errors.append(f"Grid size must be a whole number from {MIN_GRID} to {MAX_GRID}.")
    try:
        count = int(ticket_count)
        if not 1 <= count <= MAX_TICKETS:
            raise ValueError
    except ValueError:
        count = DEFAULT_TICKETS
        errors.append(f"Number of tickets must be a whole number from 1 to {MAX_TICKETS}.")

    # Only songs from this host's own library can go in the pool.
    owned = {sid for sid in session.exec(select(Song.id).where(Song.owner_id == user.id)).all()}
    pool = [sid for sid in dict.fromkeys(song_ids) if sid in owned]

    generated = None
    if not errors:
        try:
            generated = await run_in_threadpool(generate_tickets, pool, size, count)
        except TicketGenerationError as exc:
            errors.append(str(exc))
    if errors:
        return _new_game_page(request, user, session, status_code=400, form=form, selected=pool, errors=errors)

    game = Game(owner_id=user.id, name=name, code=_new_code(session), grid_size=size)
    session.add(game)
    session.flush()  # assigns game.id
    session.add_all(GameSong(game_id=game.id, song_id=sid) for sid in pool)
    session.add(Round(game_id=game.id, number=1, name="Round 1"))  # default: one line, rows only
    session.add_all(
        Ticket(game_id=game.id, number=n, cells=cells) for n, cells in enumerate(generated.tickets, start=1)
    )
    session.commit()

    message = f"Created \u201c{name}\u201d with {count} tickets. Any two tickets differ by at least {generated.min_difference} song(s)."
    flash(request, message, "success")
    if generated.min_difference == 1:
        flash(request, "The song pool is small for this ticket size, so some tickets are very similar. Add songs for more variety.", "info")
    return _redirect(f"/games/{game.id}")


# ---------------------------------------------------------------- detail


@router.get("/{game_id}")
def game_detail(
    request: Request, game_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)
):
    game = owned_game(session, user, game_id)
    rounds = session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all()
    ticket_numbers = session.exec(select(Ticket.number).where(Ticket.game_id == game.id).order_by(Ticket.number)).all()
    song_count = session.exec(select(func.count(GameSong.song_id)).where(GameSong.game_id == game.id)).one()
    team_count = session.exec(select(func.count(Team.id)).where(Team.game_id == game.id)).one()
    return render(
        request,
        "game.html",
        user=user,
        game=game,
        rounds=[(r, describe_rules(r.rules(), game.grid_size)) for r in rounds],
        ticket_numbers=ticket_numbers,
        song_count=song_count,
        team_count=team_count,
        max_lines=2 * game.grid_size + 2,
    )


@router.post("/{game_id}/delete")
def delete_game(
    request: Request,
    game_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    for model in (Claim, Team, Ticket, Round, GameSong):  # children first
        session.execute(delete(model).where(model.game_id == game.id))
    session.delete(game)
    session.commit()
    flash(request, "Game deleted.", "success")
    return _redirect("/games")


# ---------------------------------------------------------------- rounds


def parse_rules(game: Game, mode: str, lines_required: str, rows: bool, columns: bool, diagonals: bool):
    errors: list[str] = []
    try:
        required = int(lines_required)
    except ValueError:
        required = 1
        errors.append("Lines required must be a whole number.")
    if mode not in (MODE_LINES, MODE_FULL_HOUSE):
        errors.append("Unknown pattern type.")
    rules = RoundRules(mode=mode, lines_required=required, rows=rows, columns=columns, diagonals=diagonals)
    if not errors:
        errors.extend(validate_rules(rules, game.grid_size))
    return rules, errors


@router.post("/{game_id}/rounds")
def add_round(
    request: Request,
    game_id: int,
    name: str = Form(""),
    mode: str = Form(MODE_LINES),
    lines_required: str = Form("1"),
    rows: bool = Form(False),
    columns: bool = Form(False),
    diagonals: bool = Form(False),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals)
    if errors:
        flash(request, errors[0], "error")
        return _redirect(f"/games/{game.id}")
    last = session.exec(select(func.max(Round.number)).where(Round.game_id == game.id)).one() or 0
    number = last + 1
    session.add(
        Round(
            game_id=game.id,
            number=number,
            name=(name.strip() or f"Round {number}")[:60],
            mode=rules.mode,
            lines_required=rules.lines_required,
            rows=rules.rows,
            columns=rules.columns,
            diagonals=rules.diagonals,
        )
    )
    session.commit()
    flash(request, "Round added.", "success")
    return _redirect(f"/games/{game.id}")


def _owned_round(session: Session, game: Game, round_id: int) -> Round:
    found = session.get(Round, round_id)
    if found is None or found.game_id != game.id:
        raise HTTPException(status_code=404, detail="Round not found")
    return found


@router.post("/{game_id}/rounds/{round_id}")
def update_round(
    request: Request,
    game_id: int,
    round_id: int,
    name: str = Form(""),
    mode: str = Form(MODE_LINES),
    lines_required: str = Form("1"),
    rows: bool = Form(False),
    columns: bool = Form(False),
    diagonals: bool = Form(False),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    target = _owned_round(session, game, round_id)
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals)
    if errors:
        flash(request, errors[0], "error")
        return _redirect(f"/games/{game.id}")
    target.name = (name.strip() or f"Round {target.number}")[:60]
    target.mode = rules.mode
    target.lines_required = rules.lines_required
    target.rows, target.columns, target.diagonals = rules.rows, rules.columns, rules.diagonals
    session.add(target)
    session.commit()
    flash(request, f"Saved {target.name}.", "success")
    return _redirect(f"/games/{game.id}")


@router.post("/{game_id}/rounds/{round_id}/delete")
def delete_round(
    request: Request,
    game_id: int,
    round_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    target = _owned_round(session, game, round_id)
    if game.status != "draft" and target.number <= game.current_round:
        flash(request, "Rounds that have been played, or are being played, can't be deleted.", "error")
        return _redirect(f"/games/{game.id}")
    rounds = session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all()
    if len(rounds) <= 1:
        flash(request, "A game needs at least one round.", "error")
        return _redirect(f"/games/{game.id}")
    session.delete(target)
    session.flush()
    for position, remaining in enumerate((r for r in rounds if r.id != target.id), start=1):
        if remaining.number != position:  # close the gap, in ascending order
            remaining.number = position
            session.add(remaining)
    session.commit()
    flash(request, "Round deleted.", "success")
    return _redirect(f"/games/{game.id}")


# ---------------------------------------------------------------- tickets


@router.get("/{game_id}/tickets/{number}")
def ticket_view(
    request: Request,
    game_id: int,
    number: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    game = owned_game(session, user, game_id)
    ticket = session.exec(select(Ticket).where(Ticket.game_id == game.id, Ticket.number == number)).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(ticket.cells))).all()}
    size = game.grid_size
    grid = [[songs.get(sid) for sid in ticket.cells[r * size:(r + 1) * size]] for r in range(size)]
    total = session.exec(select(func.count(Ticket.id)).where(Ticket.game_id == game.id)).one()
    return render(
        request,
        "ticket.html",
        user=user,
        game=game,
        number=number,
        grid=grid,
        size=size,
        total=total,
    )
