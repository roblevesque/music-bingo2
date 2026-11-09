import hashlib
import io
import json
import zipfile

from sqlmodel import Session, select

from app.models import Game, Song, Ticket
from app.services.gameio import sha256_file
from tests.conftest import (
    add_user, all_songs, create_game, csrf_token, game_id_from, login, new_player, seed_songs,
)


def make_game(app, host, tmp_path, name="Pub Night"):
    ids = seed_songs(app, host, tmp_path, 12)
    return game_id_from(create_game(host, ids, name=name, grid_size=3, tickets=4))


def export(host, game_id, audio="1"):
    response = host.get(f"/games/{game_id}/export?audio={audio}")
    assert response.status_code == 200
    return response


def upload_bundle(client, data, name="game.musicbingo.zip"):
    return client.post("/games/import", data={"csrf_token": csrf_token(client, "/games")},
                       files={"bundle": (name, data, "application/zip")}, follow_redirects=False)


def titles_of(app, game_id):
    with Session(app.state.engine) as session:
        songs = {s.id: s.title for s in session.exec(select(Song)).all()}
        tickets = session.exec(select(Ticket).where(Ticket.game_id == game_id).order_by(Ticket.number)).all()
        return [[songs[c] for c in t.cells] for t in tickets]


def second_host(app):
    add_user(app, "other")
    client = new_player(app)
    login(client, "other")
    return client


def test_export_with_audio_is_a_complete_zip(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    response = export(logged_in, game_id)
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="Pub-Night.musicbingo.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert sum(n.startswith("clips/") for n in z.namelist()) == 12
    assert manifest["game"] == {"name": "Pub Night", "grid_size": 3}
    assert len(manifest["songs"]) == 12 and len(manifest["tickets"]) == 4 and len(manifest["rounds"]) == 1
    assert all(len(t["cells"]) == 9 for t in manifest["tickets"])


def test_export_without_audio_has_only_the_manifest(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    with zipfile.ZipFile(io.BytesIO(export(logged_in, game_id, audio="0").content)) as z:
        assert z.namelist() == ["manifest.json"]
        assert all(s["sha256"] for s in json.loads(z.read("manifest.json"))["songs"])


def test_checksums_in_an_export_match_the_audio_even_after_retagging(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    song = all_songs(app)[0]
    logged_in.post(f"/library/{song.id}/edit", data={"title": "Retagged", "write_tags_to_file": "on",
                                                     "csrf_token": csrf_token(logged_in, f"/library/{song.id}/edit")})
    with zipfile.ZipFile(io.BytesIO(export(logged_in, game_id).content)) as z:
        manifest = json.loads(z.read("manifest.json"))
        for entry in manifest["songs"]:
            assert hashlib.sha256(z.read(entry["clip"])).hexdigest() == entry["sha256"]


def test_uploads_record_their_checksum(app, logged_in, tmp_path):
    seed_songs(app, logged_in, tmp_path, 1)
    song = all_songs(app)[0]
    assert song.sha256 == sha256_file(app.state.settings.clips_dir / song.filename)


def test_only_the_owner_can_export(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    assert second_host(app).get(f"/games/{game_id}/export").status_code == 404


def test_import_into_another_account_recreates_the_game_with_the_same_tickets(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    bundle = export(logged_in, original).content
    other = second_host(app)
    response = upload_bundle(other, bundle)
    assert response.status_code == 303
    new_id = int(response.headers["location"].rsplit("/", 1)[1])
    with Session(app.state.engine) as session:
        old, new = session.get(Game, original), session.get(Game, new_id)
        mine = session.exec(select(Song).where(Song.owner_id == new.owner_id)).all()
    assert new.owner_id != old.owner_id and new.code != old.code and new.status == "draft"
    assert (new.name, new.grid_size, new.series_id, new.run_number) == (old.name, old.grid_size, None, 1)
    assert len(mine) == 12 and all(s.sha256 and (app.state.settings.clips_dir / s.filename).is_file() for s in mine)
    assert titles_of(app, new_id) == titles_of(app, original)  # the very same tickets: printed copies still work
    assert "12 song(s) added" in other.get(f"/games/{new_id}").text


def test_importing_your_own_export_reuses_the_songs_you_already_have(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    response = upload_bundle(logged_in, export(logged_in, original).content)
    new_id = int(response.headers["location"].rsplit("/", 1)[1])
    assert len(all_songs(app)) == 12  # nothing duplicated
    with Session(app.state.engine) as session:
        old = [t.cells for t in session.exec(select(Ticket).where(Ticket.game_id == original).order_by(Ticket.number)).all()]
        new = [t.cells for t in session.exec(select(Ticket).where(Ticket.game_id == new_id).order_by(Ticket.number)).all()]
    assert old == new  # the same song ids, because the same songs were found
    assert "0 song(s) added to your library, 12 already there" in logged_in.get(f"/games/{new_id}").text


def test_an_export_without_audio_imports_where_the_songs_already_exist(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    response = upload_bundle(logged_in, export(logged_in, original, audio="0").content)
    assert response.status_code == 303 and "/games/" in response.headers["location"]


def test_an_export_without_audio_fails_cleanly_where_the_songs_are_missing(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    bundle = export(logged_in, original, audio="0").content
    other = second_host(app)
    response = upload_bundle(other, bundle)
    assert response.headers["location"] == "/games"
    page = other.get("/games").text  # flash messages show once, so read the page once
    assert "Import failed" in page and "no audio for 12 song" in page
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Game)).all()) == 1  # nothing was created
        assert session.exec(select(Song).where(Song.owner_id != 1)).all() == []
    assert not [p for p in app.state.settings.clips_dir.iterdir() if p.name not in {s.filename for s in all_songs(app)}]


def test_bad_files_are_refused_and_leave_nothing_behind(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    clips_before = sorted(p.name for p in app.state.settings.clips_dir.iterdir())
    for junk in (b"not a zip at all", b"", export(logged_in, original).content[:200]):
        assert upload_bundle(logged_in, junk).headers["location"] == "/games"
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "musicbingo-game", "version": 1}))
    assert upload_bundle(logged_in, broken.getvalue()).headers["location"] == "/games"
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Game)).all()) == 1
    assert sorted(p.name for p in app.state.settings.clips_dir.iterdir()) == clips_before


def test_a_tampered_audio_file_is_caught_by_its_checksum(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    bundle = export(logged_in, original).content
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as source, zipfile.ZipFile(tampered, "w") as out:
        for item in source.infolist():
            data = source.read(item)
            out.writestr(item.filename, data + b"tampered" if item.filename == "clips/0.mp3" else data)
    other = second_host(app)
    assert upload_bundle(other, tampered.getvalue()).headers["location"] == "/games"
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Game)).all()) == 1
        assert session.exec(select(Song).where(Song.owner_id != 1)).all() == []  # rolled back, nothing half-imported


def test_the_size_limit_applies(app, logged_in, tmp_path):
    original = make_game(app, logged_in, tmp_path)
    bundle = export(logged_in, original).content
    object.__setattr__(app.state.settings, "max_import_bytes", 1000)
    assert upload_bundle(logged_in, bundle).headers["location"] == "/games"
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Game)).all()) == 1


def test_import_page_redirects_to_the_games_list(logged_in):
    assert logged_in.get("/games/import", follow_redirects=False).headers["location"] == "/games"
