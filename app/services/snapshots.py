"""JSON snapshots of a running game, sent to players and to the host console.

The player snapshot deliberately contains no song titles or ids: players must hear
the music, not read it. Only the host snapshot names the songs that were played.
"""

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Claim, Game, GameSong, Round, Song, Team, Ticket
from app.services.events import HOST, PLAYERS, Event, Hub
from app.services.patterns import describe_rules
from app.services.playlist import played_ids


def audio_url(song_id: int) -> str:
    return f"/library/{song_id}/audio"


def round_name(r: Round) -> str:
    return r.name or f"Round {r.number}"


def _rounds(session: Session, game: Game) -> list[Round]:
    return list(session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all())


def _round_view(r: Round, size: int) -> dict:
    return {
        "id": r.id,
        "number": r.number,
        "name": round_name(r),
        "text": describe_rules(r.rules(), size),
        "mode": r.mode,
        "lines_required": r.lines_required,
        "rows": r.rows,
        "columns": r.columns,
        "diagonals": r.diagonals,
    }


def _winners(session: Session, game: Game) -> list[dict]:
    rows = session.exec(
        select(Claim, Team.name)
        .join(Team, Team.id == Claim.team_id)
        .where(Claim.game_id == game.id, Claim.status == "win")
        .order_by(Claim.id)
    ).all()
    by_round: dict[int, dict] = {}
    for claim, team_name in rows:
        entry = by_round.setdefault(
            claim.round_number, {"round": claim.round_number, "round_name": claim.round_name, "teams": []}
        )
        entry["teams"].append(team_name)
    return list(by_round.values())


def _pool_size(session: Session, game: Game) -> int:
    return session.exec(select(func.count(GameSong.song_id)).where(GameSong.game_id == game.id)).one()


def public_state(session: Session, game: Game) -> dict:
    rounds = _rounds(session, game)
    current = next((r for r in rounds if r.number == game.current_round), None)
    return {
        "status": game.status,
        "round": _round_view(current, game.grid_size) if current else None,
        "songs_played": game.current_index,
        "total_songs": len(game.play_order) or _pool_size(session, game),
        "winners": _winners(session, game),
    }


def host_state(session: Session, game: Game, join_url: str) -> dict:
    order = list(game.play_order)
    songs = {}
    if order:
        songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(order))).all()}

    def song_view(song_id: int) -> dict | None:
        song = songs.get(song_id)
        if song is None:
            return None
        return {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "audio_url": audio_url(song.id),
            "start_ms": song.start_ms,
            "end_ms": song.end_ms,
        }

    played = played_ids(order, game.current_index)
    rounds = _rounds(session, game)
    current = next((r for r in rounds if r.number == game.current_round), None)
    teams = session.exec(
        select(Team, Ticket.number).join(Ticket, Ticket.id == Team.ticket_id).where(Team.game_id == game.id).order_by(Team.id)
    ).all()
    claims = session.exec(
        select(Claim, Team.name, Ticket.number)
        .join(Team, Team.id == Claim.team_id)
        .join(Ticket, Ticket.id == Team.ticket_id)
        .where(Claim.game_id == game.id, Claim.round_number == game.current_round)
        .order_by(Claim.id.desc())
    ).all()
    return {
        "game": {"id": game.id, "name": game.name, "code": game.code, "status": game.status, "grid_size": game.grid_size},
        "join_url": join_url,
        "round": _round_view(current, game.grid_size) if current else None,
        "rounds": [_round_view(r, game.grid_size) for r in rounds],
        "songs_played": game.current_index,
        "total_songs": len(order) or _pool_size(session, game),
        "current_song": song_view(played[-1]) if played else None,
        "next_song": song_view(order[game.current_index]) if game.current_index < len(order) else None,
        "played": [
            {"n": n, **view}
            for n, view in reversed([(i + 1, song_view(sid)) for i, sid in enumerate(played)])
            if view
        ],
        "teams": [{"id": team.id, "name": team.name, "ticket": number} for team, number in teams],
        "claims": [
            {"id": c.id, "team": name, "ticket": number, "status": c.status, "songs_played": c.songs_played, "detail": c.detail}
            for c, name, number in claims
        ],
        "winners": _winners(session, game),
    }


def broadcast(hub: Hub, session: Session, game: Game, join_url: str) -> None:
    """Push fresh snapshots to everyone watching this game."""
    hub.publish(game.id, PLAYERS, Event("state", public_state(session, game)))
    hub.publish(game.id, HOST, Event("state", host_state(session, game, join_url)))
