from sqlmodel import Session, select

from app.models import User
from tests.conftest import PASSWORD, add_user, csrf_token, login


def test_root_redirects_to_setup_when_no_users(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


def test_setup_creates_first_host_and_logs_in(app, client):
    response = client.post(
        "/setup",
        data={"username": "Host", "password": PASSWORD, "confirm": PASSWORD,
              "csrf_token": csrf_token(client, "/setup")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/library"
    with Session(app.state.engine) as session:
        user = session.exec(select(User)).one()
    assert user.username == "host"  # normalised to lower case
    assert user.password_hash != PASSWORD  # stored hashed
    assert client.get("/library", follow_redirects=False).status_code == 200


def test_setup_validates_input(client):
    response = client.post(
        "/setup",
        data={"username": "x", "password": "short", "confirm": "different",
              "csrf_token": csrf_token(client, "/setup")},
    )
    assert response.status_code == 400
    assert "at least 10 characters" in response.text


def test_setup_closed_once_a_host_exists(app, client):
    add_user(app)
    response = client.get("/setup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_and_logout(app, client):
    add_user(app)
    login(client)
    assert client.get("/library", follow_redirects=False).status_code == 200
    client.post("/logout", data={"csrf_token": csrf_token(client, "/library")})
    assert client.get("/library", follow_redirects=False).status_code == 303


def test_login_rejects_wrong_password_and_unknown_user(app, client):
    add_user(app)
    for username, password in [("host", "wrong password!"), ("nobody", PASSWORD)]:
        response = client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": csrf_token(client)},
        )
        assert response.status_code == 401
        assert "Incorrect username or password" in response.text


def test_library_requires_login_and_remembers_destination(client):
    response = client.get("/library", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Flibrary"


def test_post_without_csrf_token_is_rejected(app, client):
    add_user(app)
    login(client)
    assert client.post("/logout", data={}).status_code == 403


def test_login_next_cannot_redirect_off_site(app, client):
    add_user(app)
    response = client.post(
        "/login",
        data={"username": "host", "password": PASSWORD, "next": "//evil.example",
              "csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/library"
