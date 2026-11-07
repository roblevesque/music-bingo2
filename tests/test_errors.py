from tests.conftest import create_game, game_id_from, seed_songs, host_post, join_game, new_player  # noqa: F401

HTML = {"Accept": "text/html,application/xhtml+xml"}


def test_browsers_get_a_friendly_page_for_missing_things(client):
    response = client.get("/no/such/page", headers=HTML)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "We couldn&#39;t find that page" in response.text or "We couldn't find that page" in response.text
    assert 'href="/"' in response.text


def test_scripts_still_get_json_errors(client):
    response = client.get("/no/such/page")  # no text/html in Accept, like our own fetch() calls
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()


def test_unknown_game_code_page(client):
    response = client.get("/play/ZZZZZZ", headers=HTML)
    assert response.status_code == 404 and "Game not found" in response.text


def test_missing_csrf_token_explains_what_to_do(app, running_game):
    _host, _game_id, code = running_game
    response = new_player(app).post("/logout", data={}, headers=HTML)
    assert response.status_code == 403 and "out of date" in response.text


def test_invalid_form_gets_a_friendly_page(app, running_game):
    _host, _game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Typists")
    response = player.post(f"/play/{code}/mark", data={}, headers=HTML)  # no position at all
    assert response.status_code == 422 and "missing or invalid" in response.text
    assert player.post(f"/play/{code}/mark", data={}).headers["content-type"].startswith("application/json")


def test_not_joined_gets_a_403_page(app, running_game):
    _host, _game_id, code = running_game
    response = new_player(app).get(f"/play/{code}/events", headers=HTML)
    assert response.status_code == 403 and "join the game first" in response.text


def test_error_pages_do_not_leak_details(client):
    response = client.get("/no/such/page", headers=HTML)
    assert "Traceback" not in response.text and "app/" not in response.text
