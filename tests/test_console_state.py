from tests.conftest import get_game, host_post


def state(host, game_id):
    return host.get(f"/games/{game_id}/run/state").json()


def test_before_the_game_starts_there_is_no_play_order(app, logged_in, tmp_path):
    from tests.conftest import create_game, game_id_from, seed_songs
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3))
    assert state(logged_in, game_id)["upcoming"] == []


def test_the_whole_remaining_playlist_is_listed_in_play_order(app, running_game):
    host, game_id, _code = running_game
    order = get_game(app, game_id).play_order
    upcoming = state(host, game_id)["upcoming"]
    assert [s["id"] for s in upcoming] == order  # everything, in the order it will be played
    assert [s["n"] for s in upcoming] == list(range(1, 13))
    assert all({"title", "artist", "audio_url"} <= set(s) for s in upcoming)
    assert upcoming[0]["id"] == state(host, game_id)["next_song"]["id"]


def test_playing_songs_moves_them_from_upcoming_to_played(app, running_game):
    host, game_id, _code = running_game
    order = get_game(app, game_id).play_order
    for _ in range(3):
        host_post(host, game_id, "next")
    snapshot = state(host, game_id)
    assert [s["id"] for s in snapshot["upcoming"]] == order[3:]
    assert snapshot["upcoming"][0]["n"] == 4 and snapshot["played"][0]["n"] == 3
    assert len(snapshot["upcoming"]) + len(snapshot["played"]) == snapshot["total_songs"]


def test_skip_and_reshuffle_show_up_in_the_playlist(app, running_game):
    host, game_id, _code = running_game
    host_post(host, game_id, "next")
    before = [s["id"] for s in state(host, game_id)["upcoming"]]
    host_post(host, game_id, "skip")
    after_skip = [s["id"] for s in state(host, game_id)["upcoming"]]
    assert after_skip == before[1:] + before[:1]  # the skipped song is now last
    host_post(host, game_id, "reshuffle")
    after_shuffle = [s["id"] for s in state(host, game_id)["upcoming"]]
    assert sorted(after_shuffle) == sorted(before) and len(after_shuffle) == len(before)


def test_the_console_page_has_the_playlist_and_the_bingo_banner(running_game):
    host, game_id, _code = running_game
    page = host.get(f"/games/{game_id}/run").text
    for element in ('id="upcoming"', 'id="upcoming-count"', 'id="claim-alert"', 'class="console-grid"'):
        assert element in page


def test_players_never_receive_the_playlist(app, running_game):
    from app.services.snapshots import public_state
    from sqlmodel import Session
    _host, game_id, _code = running_game
    with Session(app.state.engine) as session:
        assert "upcoming" not in public_state(session, get_game(app, game_id))
