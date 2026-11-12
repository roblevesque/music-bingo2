from sqlalchemy import inspect, text

from app.db import apply_additive_migrations, make_engine
from app.services.events import HOST, REMOTE
from tests.conftest import all_songs, create_game, csrf_token, game_id_from, get_game, host_post, join_game, new_player


def turn_on(host, game_id, mode="on"):
    response = host_post(host, game_id, "remote", mode=mode)
    assert response.status_code == 200
    return response.json()["remote"]


def pair(phone, code):
    return phone.post("/remote", data={"code": code, "csrf_token": csrf_token(phone, "/remote")}, follow_redirects=False)


def paired_phone(app, host, game_id):
    code = turn_on(host, game_id)["code"]
    phone = new_player(app)
    assert pair(phone, code).status_code == 303
    return phone, code


def command(phone, game_id, **fields):
    data = {"csrf_token": csrf_token(phone, f"/remote/{game_id}"), **fields}
    return phone.post(f"/remote/{game_id}/command", data=data)


class FakeHub:
    """Stands in for the live-update hub: records what is published and pretends a console is (or isn't) open."""

    def __init__(self, hub, console_open=True):
        self.real, self.console_open, self.published = hub, console_open, []

    def subscriber_count(self, game_id, audience=None):
        return 1 if (audience == HOST and self.console_open) else 0

    def publish(self, game_id, audience, event):
        self.published.append((audience, event.name, event.data))

    def __getattr__(self, name):
        return getattr(self.real, name)


def with_console(app, console_open=True):
    fake = FakeHub(app.state.hub, console_open)
    app.state.hub = fake
    return fake


def test_the_remote_is_off_until_the_host_turns_it_on(app, running_game):
    host, game_id, _code = running_game
    assert host.get(f"/games/{game_id}/run/state").json()["remote"]["enabled"] is False
    assert get_game(app, game_id).remote_code == ""
    assert pair(new_player(app), "ABCDEF").status_code == 400


def test_turning_it_on_shows_a_code_and_the_address_to_open(running_game):
    host, game_id, _code = running_game
    remote = turn_on(host, game_id)
    assert remote["enabled"] and len(remote["code"]) == 6 and remote["url"].endswith("/remote") and remote["connected"] == 0
    assert turn_on(host, game_id)["code"] == remote["code"]  # turning it on again doesn't change the code
    assert turn_on(host, game_id, "new")["code"] != remote["code"]
    assert 'id="remote-card"' in host.get(f"/games/{game_id}/run").text


def test_a_phone_pairs_with_the_code_and_gets_the_control_page(app, running_game):
    host, game_id, join_code = running_game
    code = turn_on(host, game_id)["code"]
    join_game(new_player(app), join_code, "Secret Squad")
    phone = new_player(app)
    spaced = f" {code[:3].lower()}-{code[3:]} "  # typed sloppily
    response = pair(phone, spaced)
    assert response.status_code == 303 and response.headers["location"] == f"/remote/{game_id}"
    page = phone.get(f"/remote/{game_id}")
    assert page.status_code == 200 and "Pub Night" in page.text and 'id="r-next"' in page.text
    for secret in (code, join_code, "Secret Squad", "/library/"):  # nothing the host keeps to themselves reaches the phone
        assert secret not in page.text, secret


def test_wrong_codes_are_refused_and_guessing_is_slowed_down(app, running_game):
    host, game_id, _code = running_game
    code = turn_on(host, game_id)["code"]
    phone = new_player(app)
    for _ in range(8):
        assert pair(phone, "WRONG1").status_code == 400
    blocked = pair(phone, code)  # even the right code is refused while blocked
    assert blocked.status_code == 429 and "Too many wrong codes" in blocked.text
    assert phone.get(f"/remote/{game_id}", follow_redirects=False).status_code == 303  # still not paired


def test_a_successful_pairing_clears_the_failure_count(app, running_game):
    host, game_id, _code = running_game
    code = turn_on(host, game_id)["code"]
    phone = new_player(app)
    for _ in range(5):
        pair(phone, "WRONG1")
    assert pair(phone, code).status_code == 303
    for _ in range(7):
        assert pair(phone, "WRONG1").status_code == 400  # a fresh allowance of attempts, not blocked early


def test_an_unpaired_phone_gets_nothing(app, running_game):
    host, game_id, _code = running_game
    turn_on(host, game_id)
    stranger = new_player(app)
    assert stranger.get(f"/remote/{game_id}", follow_redirects=False).headers["location"] == "/remote"
    assert stranger.get(f"/remote/{game_id}/events").status_code == 403
    token = csrf_token(stranger, "/remote")
    assert stranger.post(f"/remote/{game_id}/command", data={"action": "next", "csrf_token": token}).status_code == 403


def test_a_paired_phone_cannot_use_the_hosts_controls(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    for path in (f"/games/{game_id}/run/state", f"/games/{game_id}/run", "/library", "/games", "/users"):
        assert phone.get(path, follow_redirects=False).status_code == 303, path  # sent to the login page
    token = csrf_token(phone, f"/remote/{game_id}")
    assert phone.post(f"/games/{game_id}/run/next", data={"csrf_token": token}, follow_redirects=False).status_code == 303


def test_commands_are_relayed_to_the_console(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    hub = with_console(app)
    assert command(phone, game_id, action="next", expect="3").json() == {"ok": True}
    assert command(phone, game_id, action="effect", effect="win").status_code == 200
    assert command(phone, game_id, action="pause").status_code == 200
    sent = [(aud, name, data) for aud, name, data in hub.published if name == "command"]
    assert [d["action"] for _a, _n, d in sent] == ["next", "effect", "pause"] and all(a == HOST for a, _n, _d in sent)
    assert sent[0][2]["expect"] == 3 and sent[1][2]["effect"] == "win" and all(len(d["id"]) == 12 for _a, _n, d in sent)


def test_commands_are_refused_when_the_console_is_not_open(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    hub = with_console(app, console_open=False)
    response = command(phone, game_id, action="next")
    assert response.status_code == 409 and "console isn't open" in response.json()["detail"]
    assert [p for p in hub.published if p[1] == "command"] == []  # nothing was queued up to fire later


def test_bad_commands_are_refused(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    with_console(app)
    for fields in ({"action": "end_game"}, {"action": ""}, {"action": "effect", "effect": "airhorn"},
                   {"action": "next", "expect": "-5"}, {"action": "skip", "expect_next": "soon"}):
        assert command(phone, game_id, **fields).status_code == 400, fields
    assert phone.post(f"/remote/{game_id}/command", data={"action": "next"}).status_code == 403  # no CSRF token


def test_a_new_code_disconnects_paired_phones_and_tells_them(app, running_game):
    host, game_id, _code = running_game
    phone, old_code = paired_phone(app, host, game_id)
    hub = with_console(app)
    new_code = turn_on(host, game_id, "new")["code"]
    assert (REMOTE, "revoked", {}) in hub.published
    assert phone.get(f"/remote/{game_id}", follow_redirects=False).headers["location"] == "/remote"
    assert command(phone, game_id, action="next").status_code == 403  # the old pairing no longer works
    assert pair(new_player(app), old_code).status_code == 400 and pair(new_player(app), new_code).status_code == 303


def test_turning_it_off_disconnects_everyone_and_stops_pairing(app, running_game):
    host, game_id, _code = running_game
    phone, code = paired_phone(app, host, game_id)
    hub = with_console(app)
    assert turn_on(host, game_id, "off")["enabled"] is False
    assert (REMOTE, "revoked", {}) in hub.published and get_game(app, game_id).remote_code == ""
    assert phone.get(f"/remote/{game_id}", follow_redirects=False).headers["location"] == "/remote"
    assert pair(new_player(app), code).status_code == 400


def test_a_phone_can_disconnect_itself(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    response = phone.post(f"/remote/{game_id}/leave", data={"csrf_token": csrf_token(phone, f"/remote/{game_id}")}, follow_redirects=False)
    assert response.headers["location"] == "/remote"
    assert phone.get(f"/remote/{game_id}", follow_redirects=False).headers["location"] == "/remote"


def test_every_code_is_six_characters_and_two_games_never_share_one(app, running_game):
    host, game_id, _code = running_game
    codes = {turn_on(host, game_id, "new")["code"] for _ in range(30)}
    assert len(codes) == 30 and all(len(c) == 6 and c.isalnum() for c in codes)

    songs = [song.id for song in all_songs(app)][:10]
    second_id = game_id_from(create_game(host, songs, name="Second", grid_size=3, tickets=2))
    first_code, second_code = turn_on(host, game_id)["code"], turn_on(host, second_id)["code"]
    assert first_code != second_code
    for code, expected in ((first_code, game_id), (second_code, second_id)):  # each code finds only its own game
        assert pair(new_player(app), code).headers["location"] == f"/remote/{expected}"


def test_a_repeated_or_stale_next_tap_is_ignored_by_the_server(app, running_game):
    host, game_id, _code = running_game
    assert host_post(host, game_id, "next", expect="0").status_code == 200       # the phone saw 0 songs played: advances
    stale = host_post(host, game_id, "next", expect="0")                          # a second tap with the same view
    assert stale.status_code == 409 and "already been played" in stale.json()["detail"]
    assert get_game(app, game_id).current_index == 1                              # only one song was played
    assert host_post(host, game_id, "next", expect="x").status_code == 409
    assert host_post(host, game_id, "next").status_code == 200                    # the console's own button sends no expectation


def test_a_stale_skip_is_ignored_too(app, running_game):
    host, game_id, _code = running_game
    order = get_game(app, game_id).play_order
    assert host_post(host, game_id, "skip", expect_next=str(order[1])).status_code == 409  # that isn't the next song
    assert get_game(app, game_id).play_order == order
    assert host_post(host, game_id, "skip", expect_next=str(order[0])).status_code == 200
    assert get_game(app, game_id).play_order[-1] == order[0]


def test_phase_6_databases_gain_the_remote_column(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE game (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO game (name) VALUES ('Old game')"))
    apply_additive_migrations(engine)
    assert "remote_code" in {c["name"] for c in inspect(engine).get_columns("game")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT remote_code FROM game")).scalar() == ""  # off for existing games
