"""Export a game to one file, and import one."""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, select
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_game_creator, require_user
from app.models import Game, GameSong, Round, Song, Ticket, User
from app.routes.games import _new_code, owned_game
from app.security import check_csrf
from app.services.clips import InvalidAudio, UploadTooLarge, new_stored_name, probe, save_upload
from app.services.gameio import (
    BundleError, BundleReader, GameBundle, RoundEntry, SongEntry, TicketEntry, sha256_file, write_bundle,
)
from app.web import flash

router = APIRouter(prefix="/games")


class ImportProblem(ValueError):
    """The bundle is fine but can't be turned into a game here. The message is safe to show."""


@dataclass
class ImportResult:
    game_id: int
    new_songs: int
    reused_songs: int


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def ensure_hashes(session: Session, settings, songs: list[Song], *, refresh: bool = False) -> None:
    """Fill in (or with refresh, recompute) each song's checksum from its audio file."""
    changed = False
    for song in songs:
        if song.sha256 and not refresh:
            continue
        path = settings.clips_dir / song.filename
        if path.is_file():
            digest = sha256_file(path)
            if digest != song.sha256:
                song.sha256 = digest
                session.add(song)
                changed = True
    if changed:
        session.commit()


# ---------------------------------------------------------------- export


@router.get("/{game_id}/export")
def export_game(
    request: Request,
    game_id: int,
    audio: str = "1",
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Everything needed to recreate this game elsewhere: songs, rounds and the exact tickets."""
    game = owned_game(session, user, game_id)
    settings = request.app.state.settings
    songs = list(session.exec(
        select(Song).join(GameSong, GameSong.song_id == Song.id).where(GameSong.game_id == game.id).order_by(Song.id)
    ).all())
    ensure_hashes(session, settings, songs, refresh=True)  # exact checksums, even if a file was retagged
    ref_of = {song.id: ref for ref, song in enumerate(songs)}
    rounds = session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all()
    tickets = session.exec(select(Ticket).where(Ticket.game_id == game.id).order_by(Ticket.number)).all()
    bundle = GameBundle(
        name=game.name,
        grid_size=game.grid_size,
        songs=[
            SongEntry(ref=ref_of[s.id], title=s.title, artist=s.artist, tags=s.tags, duration_ms=s.duration_ms,
                      start_ms=s.start_ms, end_ms=s.end_ms, sha256=s.sha256)
            for s in songs
        ],
        rounds=[
            RoundEntry(number=r.number, name=r.name, mode=r.mode, lines_required=r.lines_required,
                       rows=r.rows, columns=r.columns, diagonals=r.diagonals)
            for r in rounds
        ],
        tickets=[TicketEntry(number=t.number, cells=[ref_of[c] for c in t.cells]) for t in tickets],
    )
    clips = {}
    if audio != "0":
        clips = {ref_of[s.id]: settings.clips_dir / s.filename for s in songs if (settings.clips_dir / s.filename).is_file()}
    handle = tempfile.NamedTemporaryFile(prefix="export-", suffix=".zip", delete=False)
    handle.close()
    try:
        write_bundle(Path(handle.name), bundle, clips)
    except BaseException:
        os.unlink(handle.name)
        raise
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", game.name).strip("-") or "game"
    return FileResponse(
        handle.name, media_type="application/zip", filename=f"{slug}.musicbingo.zip",
        background=BackgroundTask(os.unlink, handle.name),  # remove the temporary file once it has been sent
    )


# ---------------------------------------------------------------- import


def perform_import(session: Session, settings, user: User, bundle_path: Path) -> ImportResult:
    """Create a new game from a bundle. All or nothing: on any problem nothing is left behind."""
    with BundleReader(bundle_path, max_total_bytes=settings.max_import_bytes, max_clip_bytes=settings.max_upload_bytes) as reader:
        bundle = reader.bundle
        library = list(session.exec(select(Song).where(Song.owner_id == user.id).order_by(Song.id)).all())
        ensure_hashes(session, settings, library)
        by_hash: dict[str, list[Song]] = {}
        for existing_song in library:
            if existing_song.sha256:
                by_hash.setdefault(existing_song.sha256, []).append(existing_song)
        used: set[int] = set()  # a library song fills at most one place in the game, even if two clips are identical

        def claim_existing(entry: SongEntry) -> Song | None:
            candidates = [s for s in by_hash.get(entry.sha256, []) if s.id not in used] if entry.sha256 else []
            if not candidates:
                return None
            chosen = next((s for s in candidates if s.title == entry.title), candidates[0])  # prefer the same title
            used.add(chosen.id)
            return chosen

        resolved: dict[int, Song] = {}
        missing: list[str] = []
        written: list[Path] = []
        new_songs = 0
        try:
            for entry in bundle.songs:
                existing = claim_existing(entry)
                if existing is not None:
                    resolved[entry.ref] = existing
                    continue
                if not entry.clip:
                    missing.append(entry.title)
                    continue
                stored = new_stored_name(Path(entry.clip).suffix)
                dest = settings.clips_dir / stored
                written.append(dest)
                digest = reader.copy_clip(entry, dest)
                if entry.sha256 and digest != entry.sha256:
                    raise ImportProblem(f"The audio for \u201c{entry.title}\u201d doesn't match its checksum, so the file may be damaged.")
                try:
                    info = probe(dest)
                except InvalidAudio:
                    raise ImportProblem(f"The audio for \u201c{entry.title}\u201d isn't a usable MP3 or Ogg file.") from None
                song = Song(
                    owner_id=user.id, filename=stored, original_name=Path(entry.clip).name, title=entry.title,
                    artist=entry.artist, tags=entry.tags, duration_ms=entry.duration_ms or info.duration_ms,
                    start_ms=entry.start_ms, end_ms=entry.end_ms, sha256=digest,
                )
                session.add(song)
                session.flush()
                resolved[entry.ref] = song
                by_hash.setdefault(digest, []).append(song)
                used.add(song.id)
                new_songs += 1
            if missing:
                shown = ", ".join(f"\u201c{t}\u201d" for t in missing[:5]) + (" and more" if len(missing) > 5 else "")
                raise ImportProblem(
                    f"This file has no audio for {len(missing)} song(s) that aren't in your library: {shown}. "
                    "Upload them first, or export the game again with audio included."
                )
            if len({s.id for s in resolved.values()}) != len(resolved):
                raise ImportProblem("Two songs in this game are the same recording, which tickets can't hold.")

            game = Game(owner_id=user.id, name=bundle.name, code=_new_code(session), grid_size=bundle.grid_size)
            session.add(game)
            session.flush()
            session.add_all(GameSong(game_id=game.id, song_id=song.id) for song in resolved.values())
            for r in bundle.rounds:
                session.add(Round(game_id=game.id, number=r.number, name=r.name, mode=r.mode, lines_required=r.lines_required,
                                  rows=r.rows, columns=r.columns, diagonals=r.diagonals))
            session.add_all(
                Ticket(game_id=game.id, number=t.number, cells=[resolved[ref].id for ref in t.cells]) for t in bundle.tickets
            )
            session.commit()
            return ImportResult(game_id=game.id, new_songs=new_songs, reused_songs=len(resolved) - new_songs)
        except BaseException:
            session.rollback()
            for path in written:
                path.unlink(missing_ok=True)
            raise


@router.get("/import")
def import_page():
    return _redirect("/games")  # the upload form lives on the games list


@router.post("/import")
async def import_game(
    request: Request,
    bundle: UploadFile = File(...),
    csrf_token: str = Form(""),
    user: User = Depends(require_game_creator),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    settings = request.app.state.settings
    handle, name = tempfile.mkstemp(prefix="import-", suffix=".zip")
    os.close(handle)
    path = Path(name)
    try:
        try:
            await save_upload(bundle, path, settings.max_import_bytes)
        except UploadTooLarge:
            flash(request, f"That file is larger than the {settings.max_import_bytes // (1024 * 1024)} MB limit.", "error")
            return _redirect("/games")
        try:
            result = await run_in_threadpool(perform_import, session, settings, user, path)
        except (BundleError, ImportProblem) as exc:
            flash(request, f"Import failed: {exc}", "error")
            return _redirect("/games")
    finally:
        path.unlink(missing_ok=True)
    flash(
        request,
        f"Game imported with a new join code. {result.new_songs} song(s) added to your library, "
        f"{result.reused_songs} already there.",
        "success",
    )
    return _redirect(f"/games/{result.game_id}")
