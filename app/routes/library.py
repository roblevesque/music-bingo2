"""Song library: upload, search, edit metadata and play window, delete, stream audio."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_user
from app.models import Game, GameSong, Song, User
from app.security import check_csrf
from app.services.clips import (
    ALLOWED_TYPES,
    InvalidAudio,
    UploadTooLarge,
    extension_of,
    new_stored_name,
    probe,
    save_upload,
    write_tags,
)
from app.services.parsing import format_time_ms, normalize_tags, parse_time_ms
from app.web import flash, render

router = APIRouter(prefix="/library")

MAX_TEXT = 200
DURATION_SLACK_MS = 1000  # VBR MP3 durations are estimates


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def owned_song(session: Session, user: User, song_id: int) -> Song:
    song = session.get(Song, song_id)
    if song is None or song.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


def _clip_path(request: Request, song: Song) -> Path:
    return request.app.state.settings.clips_dir / song.filename


@router.get("")
def library(
    request: Request,
    q: str = "",
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    stmt = select(Song).where(Song.owner_id == user.id).order_by(func.lower(Song.title), Song.id)
    needle = q.strip().lower()[:100]
    if needle:
        stmt = stmt.where(
            or_(
                *(
                    func.lower(column).contains(needle, autoescape=True)
                    for column in (Song.title, Song.artist, Song.tags)
                )
            )
        )
    songs = session.exec(stmt).all()
    return render(request, "library.html", user=user, songs=songs, q=q.strip())


@router.post("/upload")
async def upload(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    settings = request.app.state.settings
    added = 0
    problems: list[str] = []
    for upload_file in files:
        name = Path(upload_file.filename or "").name
        if not name:  # browsers send an empty part when no file was chosen
            continue
        ext = extension_of(name)
        if ext not in ALLOWED_TYPES:
            problems.append(f"{name}: only MP3 and Ogg files are supported")
            continue
        stored = new_stored_name(ext)
        dest = settings.clips_dir / stored
        try:
            await save_upload(upload_file, dest, settings.max_upload_bytes)
            info = await run_in_threadpool(probe, dest)
        except UploadTooLarge:
            problems.append(f"{name}: larger than {settings.max_upload_bytes // (1024 * 1024)} MB")
            continue
        except InvalidAudio as exc:
            dest.unlink(missing_ok=True)
            problems.append(f"{name}: {exc}")
            continue
        session.add(
            Song(
                owner_id=user.id,
                filename=stored,
                original_name=name,
                title=(info.title or Path(name).stem)[:MAX_TEXT],
                artist=info.artist[:MAX_TEXT],
                duration_ms=info.duration_ms,
            )
        )
        added += 1
    session.commit()
    if added:
        flash(request, f"Added {added} song{'s' if added != 1 else ''}.", "success")
    for problem in problems[:4]:
        flash(request, problem, "error")
    if not added and not problems:
        flash(request, "Choose at least one file to upload.", "error")
    return _redirect("/library")


def _form_values(song: Song) -> dict[str, str]:
    return {
        "title": song.title,
        "artist": song.artist,
        "tags": ", ".join(song.tag_list),
        "start": format_time_ms(song.start_ms) if song.start_ms else "",
        "end": format_time_ms(song.end_ms),
    }


@router.get("/{song_id}/edit")
def edit_form(
    request: Request,
    song_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    song = owned_song(session, user, song_id)
    return render(request, "edit_song.html", user=user, song=song, form=_form_values(song), errors=[])


@router.post("/{song_id}/edit")
async def edit_submit(
    request: Request,
    song_id: int,
    title: str = Form(""),
    artist: str = Form(""),
    tags: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    write_tags_to_file: bool = Form(False),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    song = owned_song(session, user, song_id)
    title, artist = title.strip(), artist.strip()
    errors: list[str] = []
    if not title:
        errors.append("Title is required.")
    if len(title) > MAX_TEXT or len(artist) > MAX_TEXT:
        errors.append(f"Title and artist must be at most {MAX_TEXT} characters.")

    start_ms: int | None = 0
    end_ms: int | None = None
    try:
        start_ms = parse_time_ms(start) or 0
    except ValueError as exc:
        errors.append(f"Start: {exc}.")
    try:
        end_ms = parse_time_ms(end)
    except ValueError as exc:
        errors.append(f"End: {exc}.")
    if not errors:
        if end_ms is not None and end_ms <= start_ms:
            errors.append("End must be after start.")
        if song.duration_ms is not None:
            if start_ms >= song.duration_ms:
                errors.append("Start is beyond the end of the track.")
            if end_ms is not None and end_ms > song.duration_ms + DURATION_SLACK_MS:
                errors.append("End is beyond the end of the track.")

    if errors:
        form = {"title": title, "artist": artist, "tags": tags, "start": start, "end": end}
        return render(
            request, "edit_song.html", status_code=400, user=user, song=song, form=form, errors=errors
        )

    if write_tags_to_file:
        try:
            await run_in_threadpool(write_tags, _clip_path(request, song), title, artist)
        except Exception:  # keep the database edit even if the file can't be retagged
            flash(request, "Saved, but the tags inside the audio file could not be updated.", "error")

    song.title, song.artist = title, artist
    song.tags = normalize_tags(tags)
    song.start_ms, song.end_ms = start_ms, end_ms
    session.add(song)
    session.commit()
    flash(request, f"Saved \u201c{song.title}\u201d.", "success")
    return _redirect("/library")


@router.post("/{song_id}/delete")
def delete_song(
    request: Request,
    song_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    song = owned_song(session, user, song_id)
    used_in = session.exec(
        select(Game.name).join(GameSong, GameSong.game_id == Game.id).where(GameSong.song_id == song.id)
    ).all()
    if used_in:
        names = ", ".join(f"\u201c{name}\u201d" for name in used_in[:3])
        flash(request, f"Can't delete \u201c{song.title}\u201d: it is in the song pool of {names}. Delete those games first.", "error")
        return _redirect("/library")
    _clip_path(request, song).unlink(missing_ok=True)
    session.delete(song)
    session.commit()
    flash(request, "Song deleted.", "success")
    return _redirect("/library")


@router.get("/{song_id}/audio")
def audio(
    request: Request,
    song_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Stream the clip. FileResponse handles HTTP Range, so seeking and preload work."""
    song = owned_song(session, user, song_id)
    path = _clip_path(request, song)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is missing")
    return FileResponse(path, media_type=ALLOWED_TYPES[path.suffix.lower()])
