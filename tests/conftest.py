import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Settings
from app.main import create_app
from app.models import Song, User
from app.security import hash_password

PASSWORD = "correct horse battery"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data"))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def csrf_token(client, path="/login"):
    """The CSRF token from a page: a hidden form field, or data-csrf on the player and console pages."""
    html = client.get(path).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html) or re.search(r'data-csrf="([^"]+)"', html)
    assert match, f"no CSRF token found on {path}"
    return match.group(1)


def add_user(app, username="host", password=PASSWORD, **flags):
    with Session(app.state.engine) as session:
        user = User(username=username, password_hash=hash_password(password), **flags)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def login(client, username="host", password=PASSWORD):
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


def all_songs(app):
    with Session(app.state.engine) as session:
        return session.exec(select(Song)).all()


def make_mp3(path, title=None, artist=None):
    """A tiny valid MPEG-1 Layer III file (~1 s), optionally with ID3 tags."""
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413  # 128 kbps, 44.1 kHz = 417 bytes
    path.write_bytes(frame * 40)
    if title or artist:
        from mutagen.id3 import ID3, TIT2, TPE1

        tags = ID3()
        if title:
            tags.add(TIT2(encoding=3, text=title))
        if artist:
            tags.add(TPE1(encoding=3, text=artist))
        tags.save(path, v2_version=3)
    return path


def upload(client, name, content, content_type="audio/mpeg"):
    return client.post(
        "/library/upload",
        data={"csrf_token": csrf_token(client, "/library")},
        files=[("files", (name, content, content_type))],
        follow_redirects=False,
    )


@pytest.fixture
def logged_in(app, client):
    add_user(app, is_admin=True)  # the first host is the administrator, as after /setup
    login(client)
    return client


def seed_songs(app, client, tmp_path, count):
    """Upload `count` songs ('song 00', 'song 01', ...) and return their ids."""
    data = make_mp3(tmp_path / "seed.mp3").read_bytes()
    for i in range(count):
        upload(client, f"song {i:02d}.mp3", data)
    return [song.id for song in all_songs(app)]


def create_game(client, song_ids, name="Pub Night", grid_size=3, tickets=5):
    return client.post(
        "/games/new",
        data={"name": name, "grid_size": str(grid_size), "ticket_count": str(tickets),
              "song_ids": [str(i) for i in song_ids],
              "csrf_token": csrf_token(client, "/games/new")},
        follow_redirects=False,
    )


def game_id_from(response):
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


# ---------------------------------------------------------------- phase 3 helpers

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.models import Claim, Game, GameSong, Team, Ticket  # noqa: E402


def new_player(app):
    """A separate browser with no host login."""
    return TestClient(app)


def join_game(player, code, name="Team A"):
    return player.post(
        "/join",
        data={"code": code, "team_name": name, "csrf_token": csrf_token(player, "/join")},
        follow_redirects=False,
    )


def host_post(client, game_id, action, **fields):
    data = {"csrf_token": csrf_token(client, f"/games/{game_id}/run")}
    data.update(fields)
    return client.post(f"/games/{game_id}/run/{action}", data=data)


def get_game(app, game_id):
    with Session(app.state.engine) as session:
        return session.get(Game, game_id)


def team_ticket(app, game_id, name):
    """(team, ticket cells) for the team with this name."""
    with Session(app.state.engine) as session:
        team = session.exec(select(Team).where(Team.game_id == game_id, Team.name == name)).one()
        return team, list(session.get(Ticket, team.ticket_id).cells)


def pool_ids(app, game_id):
    with Session(app.state.engine) as session:
        return list(session.exec(select(GameSong.song_id).where(GameSong.game_id == game_id)).all())


def set_play_order(app, game_id, first):
    """Make `first` the songs that will be played first (the rest follow)."""
    rest = [sid for sid in pool_ids(app, game_id) if sid not in first]
    with Session(app.state.engine) as session:
        game = session.get(Game, game_id)
        game.play_order = list(first) + rest
        game.current_index = 0
        session.add(game)
        session.commit()


def set_played_count(app, game_id, count):
    """Pretend the first `count` songs of the play order have been played."""
    with Session(app.state.engine) as session:
        game = session.get(Game, game_id)
        game.current_index = count
        session.add(game)
        session.commit()


def age_claims(app, seconds=60):
    """Pretend claims were made `seconds` ago, to get past the claim cooldown."""
    with Session(app.state.engine) as session:
        for claim in session.exec(select(Claim)).all():
            claim.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
            session.add(claim)
        session.commit()


def claim_bingo(player, code):
    return player.post(f"/play/{code}/claim", data={"csrf_token": csrf_token(player, f"/play/{code}")})


@pytest.fixture
def running_game(app, logged_in, tmp_path):
    """A started 3x3 game with 12 songs and 6 tickets. Returns (host client, game id, code)."""
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3, tickets=6))
    assert host_post(logged_in, game_id, "start").status_code == 200
    return logged_in, game_id, get_game(app, game_id).code
