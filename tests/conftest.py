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
    html = client.get(path).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def add_user(app, username="host", password=PASSWORD):
    with Session(app.state.engine) as session:
        user = User(username=username, password_hash=hash_password(password))
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
    add_user(app)
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
