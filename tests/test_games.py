from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Game, GameSong, Round, Ticket
from tests.conftest import (
    add_user, all_songs, create_game, csrf_token, game_id_from, login, seed_songs,
)


def rounds_of(app, game_id):
    with Session(app.state.engine) as session:
        return session.exec(select(Round).where(Round.game_id == game_id).order_by(Round.number)).all()


def round_form(client, game_id, **fields):
    data = {"name": "", "mode": "lines", "lines_required": "1", "rows": "on",
            "csrf_token": csrf_token(client, f"/games/{game_id}")}
    data.update(fields)
    return data


def test_create_game_generates_tickets_and_default_round(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3, tickets=5))
    with Session(app.state.engine) as session:
        game = session.get(Game, game_id)
        tickets = session.exec(select(Ticket).where(Ticket.game_id == game_id).order_by(Ticket.number)).all()
        pool = session.exec(select(GameSong).where(GameSong.game_id == game_id)).all()
    assert game.grid_size == 3 and len(game.code) == 6
    assert len(pool) == 12
    assert [t.number for t in tickets] == [1, 2, 3, 4, 5]
    assert all(len(t.cells) == 9 and set(t.cells) <= set(ids) for t in tickets)
    assert len({frozenset(t.cells) for t in tickets}) == 5
    first = rounds_of(app, game_id)
    assert len(first) == 1 and first[0].lines_required == 1 and first[0].rows and not first[0].columns
    page = logged_in.get(f"/games/{game_id}").text
    assert game.code in page and "1 line (rows)" in page


def test_create_game_validation(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    too_few = create_game(logged_in, ids[:5], grid_size=3)
    assert too_few.status_code == 400 and "needs 9 songs" in too_few.text
    assert create_game(logged_in, ids, grid_size=2).status_code == 400
    assert create_game(logged_in, ids, grid_size=3, tickets=0).status_code == 400
    assert create_game(logged_in, ids, name="  ").status_code == 400
    # ids that aren't this host's songs are ignored, leaving 8 valid songs (< 9)
    assert create_game(logged_in, ids[:8] + [99999], grid_size=3).status_code == 400
    with Session(app.state.engine) as session:
        assert session.exec(select(Game)).all() == []


def test_too_many_tickets_is_reported(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 10)  # C(10, 9) = 10 possible tickets
    response = create_game(logged_in, ids, grid_size=3, tickets=11)
    assert response.status_code == 400 and "different tickets are possible" in response.text


def test_ticket_page(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))
    page = logged_in.get(f"/games/{game_id}/tickets/1")
    assert page.status_code == 200 and "song " in page.text and "repeat(3, 1fr)" in page.text
    assert logged_in.get(f"/games/{game_id}/tickets/99").status_code == 404


def test_rounds_can_be_added_updated_and_deleted(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))

    add = logged_in.post(f"/games/{game_id}/rounds",
                         data=round_form(logged_in, game_id, name="Second", lines_required="2",
                                         columns="on", diagonals="on"),
                         follow_redirects=False)
    assert add.status_code == 303
    logged_in.post(f"/games/{game_id}/rounds",
                   data=round_form(logged_in, game_id, mode="full_house"), follow_redirects=False)
    rounds = rounds_of(app, game_id)
    assert [r.number for r in rounds] == [1, 2, 3]
    assert (rounds[1].name, rounds[1].lines_required, rounds[1].columns, rounds[1].diagonals) == ("Second", 2, True, True)
    assert rounds[2].mode == "full_house"

    # The host changes round 1's rules after the fact.
    update = logged_in.post(f"/games/{game_id}/rounds/{rounds[0].id}",
                            data=round_form(logged_in, game_id, name="Opener", columns="on"),
                            follow_redirects=False)
    assert update.status_code == 303
    changed = rounds_of(app, game_id)[0]
    assert changed.name == "Opener" and changed.columns

    # Deleting round 2 closes the gap in numbering.
    logged_in.post(f"/games/{game_id}/rounds/{rounds[1].id}/delete",
                   data={"csrf_token": csrf_token(logged_in, f"/games/{game_id}")}, follow_redirects=False)
    assert [r.number for r in rounds_of(app, game_id)] == [1, 2]


def test_invalid_round_rules_are_refused(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))  # 3x3: three rows exist
    for bad in ({"lines_required": "9"}, {"lines_required": "x"}, {"lines_required": "0"}, {"mode": "bogus"}):
        logged_in.post(f"/games/{game_id}/rounds", data=round_form(logged_in, game_id, **bad),
                       follow_redirects=False)
    logged_in.post(f"/games/{game_id}/rounds",
                   data={"name": "", "mode": "lines", "lines_required": "1",
                         "csrf_token": csrf_token(logged_in, f"/games/{game_id}")},  # no line types
                   follow_redirects=False)
    assert len(rounds_of(app, game_id)) == 1
    assert "Choose at least one of rows" in logged_in.get(f"/games/{game_id}").text


def test_last_round_cannot_be_deleted(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))
    only = rounds_of(app, game_id)[0]
    logged_in.post(f"/games/{game_id}/rounds/{only.id}/delete",
                   data={"csrf_token": csrf_token(logged_in, f"/games/{game_id}")}, follow_redirects=False)
    assert len(rounds_of(app, game_id)) == 1


def test_song_in_a_game_cannot_be_deleted_until_the_game_is_gone(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))
    song_id = ids[0]
    logged_in.post(f"/library/{song_id}/delete",
                   data={"csrf_token": csrf_token(logged_in, "/library")}, follow_redirects=False)
    assert len(all_songs(app)) == 12
    assert "in the song pool of" in logged_in.get("/library").text

    logged_in.post(f"/games/{game_id}/delete",
                   data={"csrf_token": csrf_token(logged_in, f"/games/{game_id}")}, follow_redirects=False)
    with Session(app.state.engine) as session:
        assert session.exec(select(Game)).all() == []
        assert session.exec(select(Ticket)).all() == []
        assert session.exec(select(GameSong)).all() == []
        assert session.exec(select(Round)).all() == []
    logged_in.post(f"/library/{song_id}/delete",
                   data={"csrf_token": csrf_token(logged_in, "/library")}, follow_redirects=False)
    assert len(all_songs(app)) == 11


def test_games_require_login(client):
    for path in ("/games", "/games/new", "/games/1"):
        assert client.get(path, follow_redirects=False).status_code == 303


def test_hosts_cannot_touch_each_others_games(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids))
    round_id = rounds_of(app, game_id)[0].id
    add_user(app, "other")
    with TestClient(app) as other:
        login(other, "other")
        token = csrf_token(other, "/games")
        assert other.get(f"/games/{game_id}").status_code == 404
        assert other.get(f"/games/{game_id}/tickets/1").status_code == 404
        for path in (f"/games/{game_id}/delete", f"/games/{game_id}/rounds",
                     f"/games/{game_id}/rounds/{round_id}", f"/games/{game_id}/rounds/{round_id}/delete"):
            assert other.post(path, data={"csrf_token": token}).status_code == 404
        assert "Pub Night" not in other.get("/games").text
    assert len(rounds_of(app, game_id)) == 1
