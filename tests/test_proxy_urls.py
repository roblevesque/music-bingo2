import re

import pytest

from tests.conftest import add_user, join_game, login, new_player

ODD_HOST = {"Host": "internal.example:8000"}  # what the app sees if a proxy forgets to pass the real Host header


def check_page(html):
    """Every URL in the page must be on the current origin, whatever Host the app was reached with."""
    urls = re.findall(r'(?:src|href|action)="([^"]+)"', html)
    assert [u for u in urls if u.startswith(("http://", "https://", "//"))] == []
    assert 'href="/static/styles.css"' in html and 'src="/static/app.js"' in html
    # The odd host must not reach the markup. The console's embedded JSON state is the one place it may appear:
    # it carries the join link, which is built from the request unless MUSICBINGO_PUBLIC_URL is set (and is
    # only displayed text, never a URL the browser loads).
    assert "internal.example" not in re.sub(r'<script type="application/json".*?</script>', "", html, flags=re.S)


@pytest.mark.parametrize("path", ["/login", "/join"])
def test_public_pages_do_not_depend_on_the_host_header(client, path):
    response = client.get(path, headers=ODD_HOST)
    assert response.status_code == 200
    check_page(response.text)


def test_host_pages_do_not_depend_on_the_host_header(running_game):
    host, game_id, _code = running_game
    for path in ("/library", "/games", "/games/new", "/branding", "/users", "/account",
                 f"/games/{game_id}", f"/games/{game_id}/run", f"/games/{game_id}/tickets/1"):
        response = host.get(path, headers=ODD_HOST)
        assert response.status_code == 200, path
        check_page(response.text)


def test_the_player_page_does_not_depend_on_the_host_header(app, running_game):
    _host, _game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Proxy Team")
    response = player.get(f"/play/{code}", headers=ODD_HOST)
    assert response.status_code == 200 and 'src="/static/play.js"' in response.text
    check_page(response.text)


def test_error_pages_do_not_depend_on_the_host_header(client):
    response = client.get("/no/such/page", headers={**ODD_HOST, "Accept": "text/html"})
    assert response.status_code == 404
    check_page(response.text)


def test_join_links_follow_the_public_address_setting(app, running_game):
    host, game_id, code = running_game
    state = lambda: host.get(f"/games/{game_id}/run/state", headers=ODD_HOST).json()["join_url"]
    assert state() == f"http://internal.example:8000/join/{code}"  # without the setting, whatever the proxy forwards
    object.__setattr__(app.state.settings, "public_url", "https://bingo.example.com")
    assert state() == f"https://bingo.example.com/join/{code}"


def test_the_current_section_is_marked_in_the_navigation(logged_in):
    for path, label in (("/library", "Library"), ("/games", "Games"), ("/branding", "Branding"), ("/users", "Users")):
        html = logged_in.get(path).text
        assert f'aria-current="page">{label}</a>' in html, path
        assert html.count('aria-current="page"') == 1


def test_game_pages_count_as_the_games_section(running_game):
    host, game_id, _code = running_game
    for path in (f"/games/{game_id}", f"/games/{game_id}/run", "/games/new"):
        assert 'aria-current="page">Games</a>' in host.get(path).text


def test_only_administrators_see_the_users_tab(app, logged_in):
    assert 'href="/users"' in logged_in.get("/library").text
    add_user(app, "plain")
    other = new_player(app)
    login(other, "plain")
    assert 'href="/users"' not in other.get("/library").text
