"""Audio files: validation, metadata and tag writing. No ffmpeg required."""

import uuid
from dataclasses import dataclass
from pathlib import Path

import mutagen
from fastapi import UploadFile

ALLOWED_TYPES = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".oga": "audio/ogg"}
CHUNK = 1024 * 1024


class InvalidAudio(Exception):
    """The file isn't a readable MP3/Ogg file."""


class UploadTooLarge(Exception):
    pass


@dataclass(frozen=True)
class Probe:
    title: str
    artist: str
    duration_ms: int | None


def extension_of(name: str) -> str:
    return Path(name).suffix.lower()


def new_stored_name(ext: str) -> str:
    return f"{uuid.uuid4().hex}{ext}"


async def save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Stream an upload to disk, enforcing a size limit and cleaning up on failure."""
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge()
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return size


def _first(tags, key: str) -> str:
    try:
        values = tags.get(key)
    except Exception:  # mutagen tag classes differ in how they report a missing key
        return ""
    return str(values[0]).strip() if values else ""


def probe(path: Path) -> Probe:
    """Confirm the file is real audio and read its tags and duration."""
    try:
        audio = mutagen.File(str(path), easy=True)
    except Exception as exc:  # mutagen raises many error types on corrupt input
        raise InvalidAudio("could not be read as audio") from exc
    if audio is None or not any(mime.startswith("audio/") for mime in audio.mime):
        raise InvalidAudio("is not a supported audio file")
    tags = audio.tags or {}
    length = getattr(audio.info, "length", 0) or 0
    return Probe(
        title=_first(tags, "title"),
        artist=_first(tags, "artist"),
        duration_ms=round(length * 1000) if length > 0 else None,
    )


def write_tags(path: Path, title: str, artist: str) -> None:
    """Write title/artist into the file's own tags (ID3 for MP3, Vorbis comments for Ogg)."""
    audio = mutagen.File(str(path), easy=True)
    if audio is None:
        raise InvalidAudio("is not a supported audio file")
    if audio.tags is None:
        audio.add_tags()
    audio.tags["title"] = [title]
    if artist:
        audio.tags["artist"] = [artist]
    elif "artist" in audio.tags:
        del audio.tags["artist"]
    audio.save()
