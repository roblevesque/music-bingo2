"""Consistent backups of the data directory.

    python -m app.backup create  [--data-dir DIR] [--out DIR] [--keep N]
    python -m app.backup restore ARCHIVE [--data-dir DIR] [--force]

Copying bingo.db3 while the app is running can miss recent changes (SQLite keeps them in a
side file for a while). `create` uses SQLite's own online-backup API, so the copy is consistent
even mid-game. The archive holds the database, the uploaded clips, ticket logos and the session key.
It does not import the web framework, so it also works from a bare Python install.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

DB_NAME = "bingo.db3"
KEY_NAME = "secret_key"
CLIPS_NAME = "clips"
BRANDING_NAME = "branding"
ARCHIVE_PREFIX = "musicbingo-backup-"
ALLOWED_TOP_LEVEL = {DB_NAME, KEY_NAME, CLIPS_NAME, BRANDING_NAME}


def _stamp(now: float | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))


def database_is_healthy(path: Path) -> bool:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def create_backup(data_dir: Path, out_dir: Path, now: float | None = None) -> Path:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    database = data_dir / DB_NAME
    if not database.is_file():
        raise FileNotFoundError(f"No database found at {database}. Is --data-dir right?")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{ARCHIVE_PREFIX}{_stamp(now)}.tar.gz"

    with tempfile.TemporaryDirectory() as scratch:
        snapshot = Path(scratch) / DB_NAME
        source = sqlite3.connect(database)
        copy = sqlite3.connect(snapshot)
        try:
            source.backup(copy)  # SQLite's online backup: safe while the app is writing
        finally:
            copy.close()
            source.close()
        if not database_is_healthy(snapshot):
            raise RuntimeError("The database failed SQLite's integrity check; not writing a backup.")
        with tarfile.open(target, "w:gz") as archive:
            archive.add(snapshot, arcname=DB_NAME)
            if (data_dir / KEY_NAME).is_file():
                archive.add(data_dir / KEY_NAME, arcname=KEY_NAME)
            if (data_dir / CLIPS_NAME).is_dir():
                archive.add(data_dir / CLIPS_NAME, arcname=CLIPS_NAME)
            if (data_dir / BRANDING_NAME).is_dir():
                archive.add(data_dir / BRANDING_NAME, arcname=BRANDING_NAME)
    return target


def prune_backups(out_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups made by this tool. Returns what was removed."""
    archives = sorted(Path(out_dir).glob(f"{ARCHIVE_PREFIX}*.tar.gz"))  # the timestamp sorts oldest first
    stale = archives[:-keep] if keep > 0 else []
    for path in stale:
        path.unlink()
    return stale


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Only plain files and folders, under the three names we create. Rejects anything sneaky."""
    members = archive.getmembers()
    for member in members:
        parts = Path(member.name).parts
        top_level = parts[0] if parts else ""
        if (
            Path(member.name).is_absolute()
            or ".." in parts
            or top_level not in ALLOWED_TOP_LEVEL
            or not (member.isfile() or member.isdir())
        ):
            raise ValueError(f"Refusing to restore: unexpected entry {member.name!r} in the archive.")
    if DB_NAME not in {m.name for m in members}:
        raise ValueError(f"This archive has no {DB_NAME}; it isn't a Track Bingo backup.")
    return members


def restore_backup(archive_path: Path, data_dir: Path, force: bool = False, now: float | None = None) -> Path | None:
    """Unpack a backup into data_dir. With force, existing data is moved aside (never deleted).

    Returns the folder the old data was moved to, if there was any.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    existing = [n for n in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm", KEY_NAME, CLIPS_NAME, BRANDING_NAME) if (data_dir / n).exists()]
    if existing and not force:
        raise FileExistsError(f"{data_dir} already has data ({', '.join(existing)}). Use --force to move it aside and restore.")

    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_members(archive)
        with tempfile.TemporaryDirectory(dir=data_dir) as scratch:  # unpack beside the target first
            try:
                archive.extractall(scratch, members=members, filter="data")
            except TypeError:  # Python without extraction filters (members were checked above)
                archive.extractall(scratch, members=members)
            if not database_is_healthy(Path(scratch) / DB_NAME):
                raise RuntimeError("The database in this archive failed SQLite's integrity check; nothing was restored.")
            moved_to = None
            if existing:
                moved_to = data_dir / f"before-restore-{_stamp(now)}"
                moved_to.mkdir()
                for name in existing:
                    shutil.move(str(data_dir / name), str(moved_to / name))
            for name in os.listdir(scratch):
                shutil.move(str(Path(scratch) / name), str(data_dir / name))
    return moved_to


def main(argv: list[str] | None = None) -> int:
    default_data = os.environ.get("MUSICBINGO_DATA_DIR", "data")
    parser = argparse.ArgumentParser(prog="python -m app.backup", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="write a timestamped .tar.gz backup")
    create.add_argument("--data-dir", default=default_data)
    create.add_argument("--out", default="backups")
    create.add_argument("--keep", type=int, default=0, help="keep only the newest N backups in --out (0 = keep all)")
    restore = commands.add_parser("restore", help="restore a backup into a data directory")
    restore.add_argument("archive")
    restore.add_argument("--data-dir", default=default_data)
    restore.add_argument("--force", action="store_true", help="move existing data aside and restore anyway")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            path = create_backup(Path(args.data_dir), Path(args.out))
            print(f"Backup written to {path}")
            if args.keep > 0:
                for old in prune_backups(Path(args.out), args.keep):
                    print(f"Removed old backup {old}")
        else:
            moved = restore_backup(Path(args.archive), Path(args.data_dir), force=args.force)
            print(f"Restored into {args.data_dir}")
            if moved:
                print(f"The previous data was moved to {moved}")
    except (OSError, ValueError, RuntimeError, tarfile.TarError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
