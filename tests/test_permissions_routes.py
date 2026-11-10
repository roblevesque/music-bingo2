import re

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.db import apply_additive_migrations, ensure_an_admin, make_engine
from app.models import User
from tests.conftest import (
    PASSWORD, add_user, create_game, csrf_token, game_id_from, host_post, login, new_player, seed_songs,
)


def password_from(response):
    return re.search(r'class="secret">([^<]+)<', response.text).group(1)


def create_account(admin, username="djay", **fields):
    data = {"username": username, "csrf_token": csrf_token(admin, "/users")}
    data.update(fields)
    return admin.post("/users", data=data)


def user_row(app, username):
    with Session(app.state.engine) as session:
        return session.exec(select(User).where(User.username == username)).one()


def sign_in(app, username, password):
    client = TestClient(app)
    response = client.post("/login", data={"username": username, "password": password,
                                           "csrf_token": csrf_token(client)}, follow_redirects=False)
    return client, response


def finish_password_change(client, old, new="a-brand-new-password"):
    return client.post("/account", data={"current_password": old, "new_password": new, "confirm": new,
                                         "csrf_token": csrf_token(client, "/account")}, follow_redirects=False)


def test_setup_makes_the_first_host_an_administrator(app, client):
    client.post("/setup", data={"username": "boss", "password": PASSWORD, "confirm": PASSWORD,
                                "csrf_token": csrf_token(client, "/setup")})
    assert user_row(app, "boss").is_admin and client.get("/users").status_code == 200


def test_only_administrators_can_manage_users(app, logged_in):
    add_user(app, "plain")
    other = new_player(app)
    login(other, "plain")
    assert other.get("/users").status_code == 403
    assert other.post("/users", data={"username": "x", "csrf_token": csrf_token(other, "/library")}).status_code == 403
    assert new_player(app).get("/users", follow_redirects=False).status_code == 303


def test_a_new_account_gets_a_one_time_password_and_must_change_it(app, logged_in):
    response = create_account(logged_in, "djay")
    assert response.status_code == 200 and "shown only now" in response.text
    temporary = password_from(response)
    assert user_row(app, "djay").must_change_password and temporary not in logged_in.get("/users").text

    dj, login_response = sign_in(app, "djay", temporary)
    assert login_response.status_code == 303
    forced = dj.get("/library", follow_redirects=False)  # nothing works until the password is changed
    assert forced.status_code == 303 and forced.headers["location"] == "/account"
    assert dj.get("/account").status_code == 200

    assert finish_password_change(dj, temporary).status_code == 303
    assert dj.get("/library", follow_redirects=False).status_code == 200
    assert not user_row(app, "djay").must_change_password
    assert sign_in(app, "djay", temporary)[1].status_code == 401  # the temporary one no longer works


def test_account_creation_is_validated(app, logged_in):
    assert create_account(logged_in, "x").status_code == 400
    assert create_account(logged_in, "Bad Name!").status_code == 400
    assert create_account(logged_in, "host").status_code == 400  # taken
    assert create_account(logged_in, "djay").status_code == 200
    assert create_account(logged_in, "DJAY").status_code == 400  # names are case-insensitive


def test_changing_a_password_checks_the_old_one_and_the_rules(app, logged_in):
    page = lambda **d: logged_in.post("/account", data={"csrf_token": csrf_token(logged_in, "/account"), **d})
    assert page(current_password="wrong", new_password="long-enough-pw", confirm="long-enough-pw").status_code == 400
    assert page(current_password=PASSWORD, new_password="short", confirm="short").status_code == 400
    assert page(current_password=PASSWORD, new_password="long-enough-pw", confirm="different-pw!!").status_code == 400
    assert page(current_password=PASSWORD, new_password=PASSWORD, confirm=PASSWORD).status_code == 400
    assert page(current_password=PASSWORD, new_password="long-enough-pw", confirm="long-enough-pw").status_code == 200


def test_changing_a_password_signs_out_other_sessions_but_not_this_one(app, logged_in):
    add_user(app, "multi", is_admin=False)
    laptop, _ = sign_in(app, "multi", PASSWORD)
    phone, _ = sign_in(app, "multi", PASSWORD)
    assert laptop.get("/library", follow_redirects=False).status_code == 200
    assert finish_password_change(laptop, PASSWORD).status_code == 303
    assert laptop.get("/library", follow_redirects=False).status_code == 200
    assert phone.get("/library", follow_redirects=False).status_code == 303  # ended


def test_denying_game_creation_blocks_every_way_of_making_one(app, logged_in):
    created = create_account(logged_in, "viewer")  # the "can create games" box is left unticked
    assert user_row(app, "viewer").can_create_games is False
    viewer, _ = sign_in(app, "viewer", password_from(created))
    assert finish_password_change(viewer, password_from(created)).status_code == 303

    assert viewer.get("/games/new").status_code == 403
    assert viewer.post("/games/new", data={"name": "x", "grid_size": "3", "ticket_count": "2",
                                           "csrf_token": csrf_token(viewer, "/games")}).status_code == 403
    assert viewer.post("/games/import", data={"csrf_token": csrf_token(viewer, "/games")},
                       files={"bundle": ("g.zip", b"x", "application/zip")}).status_code == 403
    page = viewer.get("/games").text
    assert "create new games" in page and 'href="/games/new"' not in page and 'action="/games/import"' not in page


def test_permissions_can_be_changed_later_and_existing_games_keep_working(app, logged_in, tmp_path):
    add_user(app, "maker")
    maker, _ = sign_in(app, "maker", PASSWORD)
    ids = seed_songs(app, maker, tmp_path, 12)
    game_id = game_id_from(create_game(maker, ids, grid_size=3, tickets=3))
    maker_id = user_row(app, "maker").id

    logged_in.post(f"/users/{maker_id}/permissions", data={"csrf_token": csrf_token(logged_in, "/users")})  # both boxes unticked
    assert user_row(app, "maker").can_create_games is False
    assert maker.get("/games/new").status_code == 403
    assert maker.get("/games").status_code == 200 and host_post(maker, game_id, "start").status_code == 200  # their game still runs

    logged_in.post(f"/users/{maker_id}/permissions", data={"can_create_games": "on", "csrf_token": csrf_token(logged_in, "/users")})
    assert maker.get("/games/new").status_code == 200


def test_the_last_administrator_cannot_be_removed(app, logged_in):
    me = user_row(app, "host").id
    token = lambda: csrf_token(logged_in, "/users")
    logged_in.post(f"/users/{me}/permissions", data={"can_create_games": "on", "csrf_token": token()})  # admin box unticked
    assert user_row(app, "host").is_admin
    assert logged_in.post(f"/users/{me}/active", data={"active": "0", "csrf_token": token()}).status_code == 200
    assert user_row(app, "host").is_active  # also can't disable yourself

    add_user(app, "second", is_admin=True)
    logged_in.post(f"/users/{me}/permissions", data={"can_create_games": "on", "csrf_token": token()})
    assert not user_row(app, "host").is_admin  # fine now: another administrator exists


def test_disabling_an_account_ends_its_sessions_and_blocks_login(app, logged_in):
    add_user(app, "temp")
    temp, _ = sign_in(app, "temp", PASSWORD)
    assert temp.get("/library", follow_redirects=False).status_code == 200
    uid = user_row(app, "temp").id
    logged_in.post(f"/users/{uid}/active", data={"active": "0", "csrf_token": csrf_token(logged_in, "/users")})
    assert temp.get("/library", follow_redirects=False).status_code == 303
    assert sign_in(app, "temp", PASSWORD)[1].status_code == 401
    logged_in.post(f"/users/{uid}/active", data={"active": "1", "csrf_token": csrf_token(logged_in, "/users")})
    assert sign_in(app, "temp", PASSWORD)[1].status_code == 303


def test_resetting_a_password_signs_the_user_out_and_issues_a_new_temporary_one(app, logged_in):
    add_user(app, "forgetful")
    user, _ = sign_in(app, "forgetful", PASSWORD)
    uid = user_row(app, "forgetful").id
    reset = logged_in.post(f"/users/{uid}/reset-password", data={"csrf_token": csrf_token(logged_in, "/users")})
    assert reset.status_code == 200 and "Password reset" in reset.text
    assert user.get("/library", follow_redirects=False).status_code == 303
    assert sign_in(app, "forgetful", PASSWORD)[1].status_code == 401
    again, response = sign_in(app, "forgetful", password_from(reset))
    assert response.status_code == 303 and again.get("/library", follow_redirects=False).headers["location"] == "/account"
    me = user_row(app, "host").id  # an administrator resets their own from the Account page instead
    own = logged_in.post(f"/users/{me}/reset-password", data={"csrf_token": csrf_token(logged_in, "/users")})
    assert "Password reset" not in own.text


def test_phase_5_databases_gain_the_permission_columns_and_an_administrator(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db3'}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)'))
        connection.execute(text('INSERT INTO "user" (username, password_hash) VALUES (\'first\', \'x\'), (\'second\', \'x\')'))
        connection.execute(text('CREATE TABLE song (id INTEGER PRIMARY KEY, title TEXT)'))
    apply_additive_migrations(engine)
    ensure_an_admin(engine)
    ensure_an_admin(engine)  # safe to repeat
    columns = {c["name"] for c in inspect(engine).get_columns("user")}
    assert {"is_admin", "can_create_games", "is_active", "must_change_password", "token_version"} <= columns
    assert "sha256" in {c["name"] for c in inspect(engine).get_columns("song")}
    with engine.connect() as connection:
        rows = connection.execute(text('SELECT username, is_admin, can_create_games, is_active FROM "user" ORDER BY id')).all()
    assert rows == [("first", 1, 1, 1), ("second", 0, 1, 1)]
