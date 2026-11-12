"""The phone remote: pair with a code shown on the host console, then send commands to that console.

A paired phone can only drive one game's console. It has no access to the host's account, the playlist,
the teams or anything else. The console, which is playing the audio, receives each command over its
live connection and acts as if the host had clicked.
"""

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Game
from app.security import check_csrf
from app.services.effects import available_effects
from app.services.events import HOST, REMOTE, Event, stream
from app.services.remote import normalize_code, validate_command
from app.services.snapshots import console_online, remote_state
from app.web import render

router = APIRouter(prefix="/remote")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _paired_game(request: Request, session: Session, game_id: int) -> Game | None:
    """The game this browser is paired with, if its code is still the current one."""
    game = session.get(Game, game_id)
    held = (request.session.get("remotes") or {}).get(str(game_id), "")
    if game is None or not game.remote_code or not held or not secrets.compare_digest(held.encode(), game.remote_code.encode()):
        return None
    return game


def _require_paired(request: Request, session: Session, game_id: int) -> Game:
    game = _paired_game(request, session, game_id)
    if game is None:
        raise HTTPException(status_code=403, detail="This phone isn't paired. Enter the code shown on the host console.")
    return game


# ---------------------------------------------------------------- pairing


def _pair_page(request: Request, *, code: str = "", error: str | None = None, status_code: int = 200):
    return render(request, "remote_pair.html", status_code=status_code, code=normalize_code(code), error=error)


@router.get("")
def pair_form(request: Request, code: str = ""):
    return _pair_page(request, code=code)


@router.post("")
async def pair_submit(request: Request, code: str = Form(""), csrf_token: str = Form(""), session: Session = Depends(get_session)):
    # async with no awaits: handled one at a time, so the in-memory limiter is never touched by two threads
    check_csrf(request, csrf_token)
    limiter = request.app.state.remote_limiter
    who = request.client.host if request.client else "unknown"
    if limiter.blocked(who):
        return _pair_page(request, code=code, status_code=429,
                          error="Too many wrong codes. Wait a few minutes, then try again.")
    typed = normalize_code(code)
    game = session.exec(select(Game).where(Game.remote_code == typed)).first() if typed else None
    if game is None:
        limiter.record_failure(who)
        return _pair_page(request, code=code, status_code=400,
                          error="That code isn't right, or the remote has been turned off on the console.")
    limiter.reset(who)
    remotes = dict(request.session.get("remotes") or {})
    remotes[str(game.id)] = game.remote_code
    request.session["remotes"] = remotes
    return _redirect(f"/remote/{game.id}")


# ---------------------------------------------------------------- control


@router.get("/{game_id}")
def control_page(request: Request, game_id: int, session: Session = Depends(get_session)):
    game = _paired_game(request, session, game_id)
    if game is None:
        return _redirect("/remote")  # not paired (or the code changed): back to the code page
    return render(request, "remote.html", game=game, state=remote_state(session, game, request.app.state.hub))


@router.post("/{game_id}/leave")
def leave(request: Request, game_id: int, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    remotes = dict(request.session.get("remotes") or {})
    remotes.pop(str(game_id), None)
    request.session["remotes"] = remotes
    return _redirect("/remote")


@router.get("/{game_id}/events")
async def events(request: Request, game_id: int, session: Session = Depends(get_session)):
    game = _require_paired(request, session, game_id)
    hub = request.app.state.hub
    subscription = hub.subscribe(game.id, REMOTE)
    hub.publish(game.id, HOST, Event("remote", {"connected": hub.subscriber_count(game.id, REMOTE)}))
    initial = [Event("state", remote_state(session, game, hub))]

    async def body():
        try:
            async for chunk in stream(subscription, initial):
                yield chunk
        finally:
            hub.unsubscribe(subscription)
            hub.publish(game.id, HOST, Event("remote", {"connected": hub.subscriber_count(game.id, REMOTE)}))

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{game_id}/command")
async def command(
    request: Request,
    game_id: int,
    action: str = Form(""),
    effect: str = Form(""),
    expect: str = Form(""),
    expect_next: str = Form(""),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    """Relay a command to the host console. Refused if the console isn't open, rather than silently lost."""
    check_csrf(request, csrf_token)
    game = _require_paired(request, session, game_id)
    hub = request.app.state.hub
    if not console_online(hub, game):
        raise HTTPException(status_code=409, detail="The host console isn't open. Open it on the host computer, then try again.")
    try:
        clean = validate_command(action, effect, expect, expect_next, [e["id"] for e in available_effects(game.owner_id)])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    hub.publish(game.id, HOST, Event("command", {"id": secrets.token_hex(6), **clean}))
    return {"ok": True}
