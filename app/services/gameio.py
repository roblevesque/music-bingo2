"""Game export and import: the portable file format. Pure Python (zipfile, json, hashlib).

A bundle is a zip holding `manifest.json` and, optionally, `clips/<ref>.<ext>` audio files:

    {"format": "musicbingo-game", "version": 1, "exported_at": "...",
     "game":    {"name": "...", "grid_size": 5},
     "songs":   [{"ref": 0, "title": "...", "artist": "...", "tags": ["pop"], "duration_ms": 1000,
                  "start_ms": 0, "end_ms": null, "sha256": "...", "clip": "clips/0.mp3" | null}],
     "rounds":  [{"number": 1, "name": "...", "mode": "lines", "lines_required": 1,
                  "rows": true, "columns": false, "diagonals": false}],
     "tickets": [{"number": 1, "cells": [<song ref>, ...]}]}

Teams, claims and play progress are not exported: a bundle is a game definition.
Everything read back is validated strictly, because a bundle may come from anywhere.
"""

import hashlib
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.services.parsing import normalize_tags
from app.services.patterns import MODES, RoundRules, validate_rules

FORMAT = "musicbingo-game"
VERSION = 1
MIN_GRID, MAX_GRID = 3, 9
MAX_SONGS, MAX_TICKETS, MAX_ROUNDS = 1000, 500, 100
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 300 * 1024 * 1024
CLIP_NAME_RE = re.compile(r"^clips/(\d{1,5})\.(mp3|ogg|oga)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


class BundleError(ValueError):
    """The file isn't a usable game bundle. The message is safe to show to the host."""


@dataclass
class SongEntry:
    ref: int
    title: str
    artist: str = ""
    tags: str = ""  # normalised, comma-separated, as the library stores it
    duration_ms: int | None = None
    start_ms: int = 0
    end_ms: int | None = None
    sha256: str = ""
    clip: str | None = None


@dataclass
class RoundEntry:
    number: int
    name: str = ""
    mode: str = "lines"
    lines_required: int = 1
    rows: bool = True
    columns: bool = False
    diagonals: bool = False


@dataclass
class TicketEntry:
    number: int
    cells: list[int] = field(default_factory=list)  # song refs, row-major


@dataclass
class GameBundle:
    name: str
    grid_size: int
    songs: list[SongEntry]
    rounds: list[RoundEntry]
    tickets: list[TicketEntry]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------------ writing


def manifest_dict(bundle: GameBundle) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "game": {"name": bundle.name, "grid_size": bundle.grid_size},
        "songs": [
            {
                "ref": s.ref, "title": s.title, "artist": s.artist,
                "tags": [t for t in s.tags.split(",") if t], "duration_ms": s.duration_ms,
                "start_ms": s.start_ms, "end_ms": s.end_ms, "sha256": s.sha256, "clip": s.clip,
            }
            for s in bundle.songs
        ],
        "rounds": [
            {
                "number": r.number, "name": r.name, "mode": r.mode, "lines_required": r.lines_required,
                "rows": r.rows, "columns": r.columns, "diagonals": r.diagonals,
            }
            for r in bundle.rounds
        ],
        "tickets": [{"number": t.number, "cells": t.cells} for t in bundle.tickets],
    }


def write_bundle(path: Path, bundle: GameBundle, clip_files: dict[int, Path] | None = None) -> None:
    """Write the zip. `clip_files` maps a song ref to its audio file; songs without one get no clip."""
    clip_files = clip_files or {}
    for song in bundle.songs:
        source = clip_files.get(song.ref)
        song.clip = f"clips/{song.ref}{Path(source).suffix.lower()}" if source else None
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest_dict(bundle), indent=2), compress_type=zipfile.ZIP_DEFLATED)
        for song in bundle.songs:
            if song.clip:  # MP3 and Ogg are already compressed, so store them as they are
                archive.write(clip_files[song.ref], arcname=song.clip, compress_type=zipfile.ZIP_STORED)


# ------------------------------------------------------------------ reading and validation


def _text(value: object, what: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise BundleError(f"{what} must be text.")
    value = " ".join(value.split())
    if required and not value:
        raise BundleError(f"{what} can't be empty.")
    if len(value) > maximum:
        raise BundleError(f"{what} is too long.")
    return value


def _int(value: object, what: str, *, minimum: int = 0, maximum: int = 10**9, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BundleError(f"{what} is not a valid number.")
    return value


def parse_manifest(data: object) -> GameBundle:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BundleError("This isn't a Track Bingo game file.")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise BundleError("This game file has no valid version.")
    if version > VERSION:
        raise BundleError("This game file was made by a newer version of Track Bingo. Please upgrade first.")

    game = data.get("game")
    if not isinstance(game, dict):
        raise BundleError("The game details are missing.")
    name = _text(game.get("name"), "The game name", maximum=100, required=True)
    size = _int(game.get("grid_size"), "The grid size", minimum=MIN_GRID, maximum=MAX_GRID)

    raw_songs = data.get("songs")
    if not isinstance(raw_songs, list) or not 1 <= len(raw_songs) <= MAX_SONGS:
        raise BundleError(f"A game needs between 1 and {MAX_SONGS} songs.")
    songs: list[SongEntry] = []
    for raw in raw_songs:
        if not isinstance(raw, dict):
            raise BundleError("A song entry is malformed.")
        ref = _int(raw.get("ref"), "A song reference", maximum=99999)
        title = _text(raw.get("title"), "A song title", maximum=200, required=True)
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise BundleError(f"The tags for \u201c{title}\u201d are malformed.")
        start = _int(raw.get("start_ms", 0), f"The start point of \u201c{title}\u201d")
        end = _int(raw.get("end_ms"), f"The end point of \u201c{title}\u201d", nullable=True)
        if end is not None and end <= start:
            raise BundleError(f"The end point of \u201c{title}\u201d is before its start.")
        digest = raw.get("sha256", "")
        if digest and not (isinstance(digest, str) and SHA256_RE.match(digest)):
            raise BundleError(f"The checksum for \u201c{title}\u201d is malformed.")
        clip = raw.get("clip")
        if clip is not None:
            match = CLIP_NAME_RE.match(clip) if isinstance(clip, str) else None
            if not match or int(match.group(1)) != ref:
                raise BundleError(f"The audio file named for \u201c{title}\u201d is not allowed.")
        songs.append(SongEntry(
            ref=ref, title=title, artist=_text(raw.get("artist", ""), "An artist name", maximum=200),
            tags=normalize_tags(",".join(tags)), duration_ms=_int(raw.get("duration_ms"), "A duration", nullable=True),
            start_ms=start, end_ms=end, sha256=digest or "", clip=clip,
        ))
    refs = [s.ref for s in songs]
    if len(set(refs)) != len(refs):
        raise BundleError("Two songs share the same reference.")
    if size * size > len(songs):
        raise BundleError(f"A {size}\u00d7{size} ticket needs at least {size * size} songs.")

    raw_rounds = data.get("rounds")
    if not isinstance(raw_rounds, list) or not 1 <= len(raw_rounds) <= MAX_ROUNDS:
        raise BundleError("A game needs at least one round.")
    rounds: list[RoundEntry] = []
    for raw in sorted((r for r in raw_rounds if isinstance(r, dict)), key=lambda r: r.get("number") if isinstance(r.get("number"), int) else 0):
        mode = raw.get("mode")
        if mode not in MODES:
            raise BundleError("A round has an unknown pattern type.")
        entry = RoundEntry(
            number=len(rounds) + 1, name=_text(raw.get("name", ""), "A round name", maximum=60), mode=mode,
            lines_required=_int(raw.get("lines_required", 1), "The lines required", minimum=1, maximum=100),
            rows=bool(raw.get("rows")), columns=bool(raw.get("columns")), diagonals=bool(raw.get("diagonals")),
        )
        problems = validate_rules(RoundRules(entry.mode, entry.lines_required, entry.rows, entry.columns, entry.diagonals), size)
        if problems:
            raise BundleError(f"Round {entry.number}: {problems[0]}")
        rounds.append(entry)
    if len(rounds) != len(raw_rounds):
        raise BundleError("A round entry is malformed.")

    raw_tickets = data.get("tickets")
    if not isinstance(raw_tickets, list) or not 1 <= len(raw_tickets) <= MAX_TICKETS:
        raise BundleError(f"A game needs between 1 and {MAX_TICKETS} tickets.")
    known, tickets, numbers = set(refs), [], set()
    for raw in raw_tickets:
        if not isinstance(raw, dict):
            raise BundleError("A ticket entry is malformed.")
        number = _int(raw.get("number"), "A ticket number", minimum=1)
        cells = raw.get("cells")
        if number in numbers:
            raise BundleError(f"Ticket {number} appears twice.")
        numbers.add(number)
        if not isinstance(cells, list) or len(cells) != size * size or not all(isinstance(c, int) and not isinstance(c, bool) for c in cells):
            raise BundleError(f"Ticket {number} doesn't have {size * size} squares.")
        if not set(cells) <= known:
            raise BundleError(f"Ticket {number} uses a song that isn't in the game.")
        if len(set(cells)) != len(cells):
            raise BundleError(f"Ticket {number} repeats a song.")
        tickets.append(TicketEntry(number=number, cells=list(cells)))
    tickets.sort(key=lambda t: t.number)
    return GameBundle(name=name, grid_size=size, songs=songs, rounds=rounds, tickets=tickets)


class BundleReader:
    """Opens a bundle safely: checks the member names and sizes before anything is read."""

    def __init__(self, path: Path, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES, max_clip_bytes: int = 50 * 1024 * 1024):
        self.max_clip_bytes = max_clip_bytes
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            raise BundleError("That file isn't a valid game bundle (it isn't a zip file).") from None
        try:
            infos = self._zip.infolist()
            names = {info.filename for info in infos}
            for info in infos:
                if info.filename != "manifest.json" and not CLIP_NAME_RE.match(info.filename):
                    raise BundleError(f"The bundle contains an unexpected file ({info.filename[:40]!r}).")
            if len(names) != len(infos):
                raise BundleError("The bundle lists the same file twice.")
            if "manifest.json" not in names:
                raise BundleError("The bundle has no manifest.json.")
            if sum(info.file_size for info in infos) > max_total_bytes:
                raise BundleError("The bundle is larger than this server accepts when unpacked.")
            manifest_info = self._zip.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise BundleError("The bundle's manifest is too large.")
            try:
                data = json.loads(self._zip.read(manifest_info).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise BundleError("The bundle's manifest couldn't be read.") from None
            self.bundle = parse_manifest(data)
            for song in self.bundle.songs:
                if song.clip and song.clip not in names:
                    raise BundleError(f"The audio file for \u201c{song.title}\u201d is missing from the bundle.")
        except BaseException:
            self._zip.close()
            raise

    def copy_clip(self, song: SongEntry, dest: Path) -> str:
        """Copy a song's audio to `dest`, enforcing the size cap. Returns its SHA-256."""
        digest, size = hashlib.sha256(), 0
        with self._zip.open(song.clip) as source, Path(dest).open("wb") as out:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                if size > self.max_clip_bytes:
                    raise BundleError(f"The audio for \u201c{song.title}\u201d is too large.")
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest()

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
