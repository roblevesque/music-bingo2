from tests.conftest import add_user, all_songs, create_game, game_id_from, login, new_player, seed_songs


def tracks(client, game_id):
    response = client.get(f"/games/{game_id}/run/background")
    assert response.status_code == 200
    return response.json()["songs"]


def test_the_whole_library_comes_back_shuffled_each_time(app, running_game):
    host, game_id, _code = running_game
    first, second = tracks(host, game_id), tracks(host, game_id)
    library = {s.id for s in all_songs(app)}
    assert {t["id"] for t in first} == {t["id"] for t in second} == library and len(first) == 12
    assert all({"title", "artist", "audio_url"} <= set(t) and t["audio_url"] == f"/library/{t['id']}/audio" for t in first)
    assert [t["id"] for t in first] != [t["id"] for t in second]  # a fresh order each time (a 1-in-479-million chance of a false failure)


def test_it_covers_the_library_not_just_the_games_song_pool(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids[:10], grid_size=3, tickets=2))  # a pool of 10 of the 12 (9 would allow only one distinct ticket)
    assert len(tracks(logged_in, game_id)) == 12


def test_a_host_only_gets_their_own_songs(app, logged_in, tmp_path):
    seed_songs(app, logged_in, tmp_path, 12)
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    theirs = seed_songs(app, other, tmp_path, 12)[12:]
    other_game = game_id_from(create_game(other, theirs, grid_size=3, tickets=2))
    assert {t["id"] for t in tracks(other, other_game)} == set(theirs)


def test_another_hosts_game_is_off_limits_and_login_is_required(app, running_game):
    host, game_id, _code = running_game
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get(f"/games/{game_id}/run/background").status_code == 404
    assert new_player(app).get(f"/games/{game_id}/run/background", follow_redirects=False).status_code == 303


def test_the_console_has_the_background_music_card(running_game):
    host, game_id, _code = running_game
    page = host.get(f"/games/{game_id}/run").text
    for element in ('id="bg-card"', 'id="bg-play"', 'id="bg-audio"', 'id="bg-volume"', 'id="bg-after"'):
        assert element in page
