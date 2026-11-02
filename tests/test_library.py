import mutagen
from fastapi.testclient import TestClient

from tests.conftest import add_user, all_songs, csrf_token, login, make_mp3, upload


def test_upload_reads_tags_and_lists_song(app, logged_in, tmp_path):
    mp3 = make_mp3(tmp_path / "a.mp3", title="Dancing Queen", artist="ABBA")
    response = upload(logged_in, "a.mp3", mp3.read_bytes())
    assert response.status_code == 303
    song = all_songs(app)[0]
    assert (song.title, song.artist) == ("Dancing Queen", "ABBA")
    assert song.duration_ms and 500 < song.duration_ms < 2000
    assert (app.state.settings.clips_dir / song.filename).is_file()
    assert "Dancing Queen" in logged_in.get("/library").text


def test_upload_without_tags_falls_back_to_file_name(app, logged_in, tmp_path):
    mp3 = make_mp3(tmp_path / "x.mp3")
    upload(logged_in, "My Great Song.mp3", mp3.read_bytes())
    assert all_songs(app)[0].title == "My Great Song"


def test_upload_rejects_non_audio(app, logged_in):
    upload(logged_in, "notes.txt", b"hello")
    upload(logged_in, "fake.mp3", b"this is not audio at all" * 50)
    assert all_songs(app) == []
    assert list(app.state.settings.clips_dir.iterdir()) == []  # nothing left behind


def test_upload_enforces_size_limit(app, logged_in, tmp_path):
    object.__setattr__(app.state.settings, "max_upload_bytes", 1000)
    upload(logged_in, "big.mp3", make_mp3(tmp_path / "big.mp3").read_bytes())
    assert all_songs(app) == []
    assert list(app.state.settings.clips_dir.iterdir()) == []


def _add_song(app, client, tmp_path):
    upload(client, "a.mp3", make_mp3(tmp_path / "a.mp3", title="Old", artist="Me").read_bytes())
    return all_songs(app)[0]


def test_edit_saves_metadata_window_and_tags(app, logged_in, tmp_path):
    song = _add_song(app, logged_in, tmp_path)
    response = logged_in.post(
        f"/library/{song.id}/edit",
        data={"title": "New Title", "artist": "New Artist", "tags": "Rock, 80s ,rock",
              "start": "0.2", "end": "0.8", "write_tags_to_file": "on",
              "csrf_token": csrf_token(logged_in, f"/library/{song.id}/edit")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    song = all_songs(app)[0]
    assert (song.title, song.artist, song.tags) == ("New Title", "New Artist", "rock,80s")
    assert (song.start_ms, song.end_ms) == (200, 800)
    tags = mutagen.File(str(app.state.settings.clips_dir / song.filename), easy=True).tags
    assert tags["title"] == ["New Title"]


def test_edit_rejects_bad_window(app, logged_in, tmp_path):
    song = _add_song(app, logged_in, tmp_path)
    for start, end in [("0.8", "0.2"), ("abc", ""), ("0", "99")]:
        response = logged_in.post(
            f"/library/{song.id}/edit",
            data={"title": "T", "start": start, "end": end,
                  "csrf_token": csrf_token(logged_in, f"/library/{song.id}/edit")},
        )
        assert response.status_code == 400
    assert all_songs(app)[0].title == "Old"  # unchanged


def test_audio_supports_range_requests(app, logged_in, tmp_path):
    song = _add_song(app, logged_in, tmp_path)
    response = logged_in.get(f"/library/{song.id}/audio", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 0-99/")


def test_search_filters_by_title_artist_and_tag(app, logged_in, tmp_path):
    _add_song(app, logged_in, tmp_path)
    assert "Old" in logged_in.get("/library?q=old").text
    assert "Old" in logged_in.get("/library?q=me").text
    assert "No songs match" in logged_in.get("/library?q=zzz").text


def test_delete_removes_row_and_file(app, logged_in, tmp_path):
    song = _add_song(app, logged_in, tmp_path)
    path = app.state.settings.clips_dir / song.filename
    logged_in.post(f"/library/{song.id}/delete",
                   data={"csrf_token": csrf_token(logged_in, "/library")})
    assert all_songs(app) == []
    assert not path.exists()


def test_hosts_cannot_touch_each_others_songs(app, logged_in, tmp_path):
    song = _add_song(app, logged_in, tmp_path)
    add_user(app, "other")
    with TestClient(app) as other:
        login(other, "other")
        assert other.get(f"/library/{song.id}/edit").status_code == 404
        assert other.get(f"/library/{song.id}/audio").status_code == 404
        response = other.post(f"/library/{song.id}/delete",
                              data={"csrf_token": csrf_token(other, "/library")})
        assert response.status_code == 404
    assert len(all_songs(app)) == 1
