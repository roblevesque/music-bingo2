from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.db import apply_additive_migrations, make_engine
from app.models import Game, GameSong, Round, Team, Ticket
from tests.conftest import (
    add_user, create_game, csrf_token, game_id_from, get_game, host_post, join_game, login, new_player,
    seed_songs,
)


def rerun(client, game_id, **fields):
    data = {"csrf_token": csrf_token(client, f"/games/{game_id}")}
    data.update(fields)
    return client.post(f"/games/{game_id}/rerun", data=data, follow_redirects=False)


def tickets_of(app, game_id):
    with Session(app.state.engine) as session:
        rows = session.exec(select(Ticket).where(Ticket.game_id == game_id).order_by(Ticket.number)).all()
        return [(t.number, list(t.cells)) for t in rows]


def finished_game(running_game):
    host, game_id, _code = running_game
    assert host_post(host, game_id, "finish").status_code == 200
    return host, game_id


def test_only_a_finished_game_can_be_run_again(app, running_game):
    host, game_id, _code = running_game  # still active
    response = rerun(host, game_id)
    assert response.headers["location"] == f"/games/{game_id}"
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Game)).all()) == 1


def test_rerun_keeps_tickets_pool_and_rounds_but_gets_a_new_code(app, running_game):
    host, game_id = finished_game(running_game)
    # The host changed round 1's rules during the first run; the copy keeps that.
    round_id = host.get(f"/games/{game_id}/run/state").json()["round"]["id"]
    host_post(host, game_id, "rules", round_id=round_id, name="Opener", mode="lines", lines_required="2",
              rows="on", columns="on")
    response = rerun(host, game_id)
    new_id = game_id_from(response)
    assert new_id != game_id

    old, new = get_game(app, game_id), get_game(app, new_id)
    assert new.code != old.code and new.status == "draft" and new.current_index == 0 and new.play_order == []
    assert (new.run_number, new.series_id, new.grid_size, new.name) == (2, game_id, old.grid_size, old.name)
    assert tickets_of(app, new_id) == tickets_of(app, game_id)  # printed tickets still valid
    with Session(app.state.engine) as session:
        pool = lambda gid: sorted(session.exec(select(GameSong.song_id).where(GameSong.game_id == gid)).all())
        assert pool(new_id) == pool(game_id)
        copied = session.exec(select(Round).where(Round.game_id == new_id)).one()
        assert (copied.name, copied.lines_required, copied.rows, copied.columns) == ("Opener", 2, True, True)
        assert session.exec(select(Team).where(Team.game_id == new_id)).all() == []


def test_rerun_can_regenerate_tickets(app, running_game):
    host, game_id = finished_game(running_game)
    new_id = game_id_from(rerun(host, game_id, regenerate="on"))
    old, new = tickets_of(app, game_id), tickets_of(app, new_id)
    assert [n for n, _ in new] == [n for n, _ in old] and new != old
    assert all(len(cells) == 9 for _n, cells in new)


def test_the_new_run_plays_like_any_other_game(app, running_game):
    host, game_id = finished_game(running_game)
    new_id = game_id_from(rerun(host, game_id))
    code = get_game(app, new_id).code
    assert join_game(new_player(app), code, "Fresh Team").status_code == 303
    assert host_post(host, new_id, "start").json()["game"]["status"] == "active"
    assert join_game(new_player(app), get_game(app, game_id).code, "Too late").status_code == 400  # old run is over


def test_the_game_list_shows_one_row_per_game(app, running_game):
    host, game_id = finished_game(running_game)
    second = game_id_from(rerun(host, game_id))
    host_post(host, second, "start")
    host_post(host, second, "finish")
    third = game_id_from(rerun(host, second))
    assert get_game(app, third).run_number == 3 and get_game(app, third).series_id == game_id
    
    listing = host.get("/games").text
    assert listing.count('<td><a href="/games/') == 1
    assert f'href="/games/{third}"' in listing and "run 3 of 3" in listing

    page = host.get(f"/games/{third}").text  # history lives on the game page
    assert f'href="/games/{game_id}"' in page and f'href="/games/{second}"' in page and "Delete this run" in page


def test_deleting_the_newest_run_brings_the_previous_one_back_to_the_list(app, running_game):
    host, game_id = finished_game(running_game)
    second = game_id_from(rerun(host, game_id))
    host.post(f"/games/{second}/delete", data={"csrf_token": csrf_token(host, f"/games/{second}")})
    listing = host.get("/games").text
    assert f'href="/games/{game_id}"' in listing and f'href="/games/{second}"' not in listing


def test_songs_in_a_rerun_game_are_named_once_in_the_delete_warning(app, running_game):
    host, game_id = finished_game(running_game)
    rerun(host, game_id)
    song_id = get_game(app, game_id).play_order[0]
    # The client follows the redirect, so the warning is in the response to this POST itself.
    response = host.post(f"/library/{song_id}/delete", data={"csrf_token": csrf_token(host, "/library")})
    assert "in the song pool of" in response.text and response.text.count("Pub Night") == 1


def test_only_the_owner_can_rerun(app, running_game):
    host, game_id = finished_game(running_game)
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.post(f"/games/{game_id}/rerun", data={"csrf_token": csrf_token(other, "/games")}).status_code == 404


def test_phase_3_databases_gain_the_series_columns(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE game (id INTEGER PRIMARY KEY, name TEXT, current_round INTEGER NOT NULL DEFAULT 1)"))
        connection.execute(text("INSERT INTO game (name) VALUES ('Old game')"))
    apply_additive_migrations(engine)
    assert {"series_id", "run_number"} <= {c["name"] for c in inspect(engine).get_columns("game")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT series_id, run_number FROM game")).one() == (None, 1)
