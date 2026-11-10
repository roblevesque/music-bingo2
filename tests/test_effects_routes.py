import pytest

from app.services.effects import available_effects


def test_the_console_state_lists_the_effects(running_game):
    host, game_id, _code = running_game
    assert host.get(f"/games/{game_id}/run/state").json()["effects"] == available_effects()


def test_the_console_has_a_place_for_effects(running_game):
    host, game_id, _code = running_game
    page = host.get(f"/games/{game_id}/run").text
    assert 'id="effects"' in page and 'id="effect-audio"' in page


@pytest.mark.parametrize("effect", available_effects(), ids=lambda e: e["id"])
def test_each_effect_file_is_served_with_range_support(client, effect):
    response = client.get(effect["url"])
    assert response.status_code == 200 and response.headers["content-type"].startswith("audio/")
    assert response.content[:4] == b"RIFF"
    ranged = client.get(effect["url"], headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100


def test_players_never_receive_the_effects_list(app, running_game):
    from sqlmodel import Session
    from app.services.snapshots import public_state
    from tests.conftest import get_game
    _host, game_id, _code = running_game
    with Session(app.state.engine) as session:
        assert "effects" not in public_state(session, get_game(app, game_id))
