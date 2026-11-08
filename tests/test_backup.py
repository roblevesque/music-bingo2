import io
import sqlite3
import tarfile
import time

import pytest

from app.backup import create_backup, main, prune_backups, restore_backup


def make_data_dir(root, rows=3):
    data = root / "data"
    (data / "clips").mkdir(parents=True)
    (data / "clips" / "a.mp3").write_bytes(b"audio-bytes")
    (data / "secret_key").write_text("s3cret")
    (data / "branding").mkdir()
    (data / "branding" / "logo-1.png").write_bytes(b"logo-bytes")
    connection = sqlite3.connect(data / "bingo.db3")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE song (id INTEGER PRIMARY KEY, title TEXT)")
    connection.executemany("INSERT INTO song (title) VALUES (?)", [(f"Song {i}",) for i in range(rows)])
    connection.commit()
    return data, connection  # connection left open, as the running app would


def count_songs(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM song").fetchone()[0]
    finally:
        connection.close()


def test_backup_includes_changes_still_in_the_wal_and_restores_everything(tmp_path):
    data, live = make_data_dir(tmp_path, rows=3)
    live.execute("INSERT INTO song (title) VALUES ('Added while running')")
    live.commit()  # sits in the -wal file; a plain copy of bingo.db3 could miss it
    archive = create_backup(data, tmp_path / "backups")
    assert archive.name.startswith("musicbingo-backup-") and archive.suffix == ".gz"

    restored = tmp_path / "restored"
    assert restore_backup(archive, restored) is None
    assert count_songs(restored / "bingo.db3") == 4
    assert (restored / "clips" / "a.mp3").read_bytes() == b"audio-bytes"
    assert (restored / "secret_key").read_text() == "s3cret"
    assert (restored / "branding" / "logo-1.png").read_bytes() == b"logo-bytes"
    live.close()


def test_backup_needs_a_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_backup(tmp_path / "empty", tmp_path / "out")


def test_restore_refuses_to_overwrite_unless_forced_and_then_keeps_the_old_data(tmp_path):
    data, live = make_data_dir(tmp_path, rows=2)
    archive = create_backup(data, tmp_path / "backups")
    live.execute("INSERT INTO song (title) VALUES ('newer')")
    live.commit()
    live.close()

    with pytest.raises(FileExistsError):
        restore_backup(archive, data)
    moved = restore_backup(archive, data, force=True)
    assert count_songs(data / "bingo.db3") == 2  # back to the backed-up state
    assert count_songs(moved / "bingo.db3") == 3  # what was there before is still available
    assert moved.name.startswith("before-restore-")


@pytest.mark.parametrize("bad_name", ["../evil.txt", "/etc/passwd", "other/file.txt", "clips/../../x"])
def test_restore_rejects_unsafe_archives(tmp_path, bad_name):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(bad_name)
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / "target")
    assert not (tmp_path / "evil.txt").exists()


def test_restore_rejects_an_archive_that_is_not_a_backup(tmp_path):
    archive = tmp_path / "notes.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("secret_key")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / "target")


def test_prune_keeps_only_the_newest_backups(tmp_path):
    data, live = make_data_dir(tmp_path)
    out = tmp_path / "backups"
    made = [create_backup(data, out, now=1_700_000_000 + 60 * n) for n in range(4)]
    (out / "unrelated.txt").write_text("keep me")
    removed = prune_backups(out, keep=2)
    assert sorted(p.name for p in removed) == sorted(p.name for p in made[:2])
    assert sorted(p.name for p in out.glob("musicbingo-backup-*")) == sorted(p.name for p in made[2:])
    assert (out / "unrelated.txt").exists()
    live.close()


def test_command_line(tmp_path, capsys):
    data, live = make_data_dir(tmp_path)
    live.close()
    assert main(["create", "--data-dir", str(data), "--out", str(tmp_path / "b"), "--keep", "5"]) == 0
    archive = next((tmp_path / "b").glob("*.tar.gz"))
    assert main(["restore", str(archive), "--data-dir", str(tmp_path / "r")]) == 0
    assert main(["restore", str(archive), "--data-dir", str(tmp_path / "r")]) == 1  # already has data
    assert "already has data" in capsys.readouterr().err
