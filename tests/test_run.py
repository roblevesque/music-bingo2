from sqlmodel import Session, select
from sqlalchemy import inspect, text

from app.db import apply_additive_migrations, make_engine
from app.models import Round
from tests.conftest import (
    add_user, age_claims, claim_bingo, csrf_token, get_game, host_post, join_game, login,
    new_player, pool_ids, set_played_count, set_play_order, team_ticket,
)


def test_console_needs_the_owning_host(app, running_game):
    _host, game_id, _code = running_game
    anonymous = new_player(app)
    assert anonymous.get(f"/games/{game_id}/run", follow_redirects=False).status_code == 303
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get(f"/games/{game_id}/run").status_code == 404
    assert other.post(f"/games/{game_id}/run/next", data={"csrf_token": csrf_token(other, "/games")}).status_code == 404


def test_actions_need_a_csrf_token(running_game):
    host, game_id, _code = running_game
    assert host.post(f"/games/{game_id}/run/next", data={}).status_code == 403


def test_start_creates_a_shuffled_play_order_once(app, logged_in, tmp_path):
    from tests.conftest import create_game, game_id_from, seed_songs
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3))
    assert host_post(logged_in, game_id, "next").status_code == 409  # not started
    started = host_post(logged_in, game_id, "start")
    assert started.status_code == 200 and started.json()["game"]["status"] == "active"
    game = get_game(app, game_id)
    assert sorted(game.play_order) == sorted(ids) and game.current_index == 0 and game.current_round == 1
    assert host_post(logged_in, game_id, "start").status_code == 409  # only once


def test_next_plays_songs_in_order_until_none_are_left(app, running_game):
    host, game_id, _code = running_game
    order = get_game(app, game_id).play_order
    first = host_post(host, game_id, "next").json()
    assert first["songs_played"] == 1
    assert first["current_song"]["id"] == order[0]
    assert first["current_song"]["audio_url"] == f"/library/{order[0]}/audio"
    assert first["next_song"]["id"] == order[1]
    for _ in range(11):
        last = host_post(host, game_id, "next")
    assert last.json()["next_song"] is None and last.json()["songs_played"] == 12
    assert host_post(host, game_id, "next").status_code == 409
    assert [p["n"] for p in last.json()["played"]][:2] == [12, 11]  # newest first


def test_skip_and_reshuffle_only_affect_unplayed_songs(app, running_game):
    host, game_id, _code = running_game
    for _ in range(3):
        host_post(host, game_id, "next")
    before = get_game(app, game_id).play_order
    assert host_post(host, game_id, "skip").status_code == 200
    skipped = get_game(app, game_id).play_order
    assert skipped[:3] == before[:3] and skipped[-1] == before[3] and sorted(skipped) == sorted(before)
    assert host_post(host, game_id, "reshuffle").status_code == 200
    after = get_game(app, game_id).play_order
    assert after[:3] == before[:3] and sorted(after) == sorted(before)


def test_host_changes_the_rules_mid_game_and_a_rejected_claim_becomes_valid(app, running_game):
    host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Columnists")
    _team, cells = team_ticket(app, game_id, "Columnists")
    column = [cells[0], cells[3], cells[6]]  # first column of a 3x3 ticket
    set_play_order(app, game_id, column)
    for _ in range(3):
        host_post(host, game_id, "next")
    assert claim_bingo(player, code).json()["status"] == "rejected"  # round 1 is rows only
    age_claims(app)

    with Session(app.state.engine) as session:
        round_id = session.exec(select(Round.id).where(Round.game_id == game_id)).first()
    changed = host_post(host, game_id, "rules", round_id=round_id, name="Rows or columns", mode="lines",
                        lines_required="1", rows="on", columns="on")
    assert changed.status_code == 200 and changed.json()["round"]["text"] == "1 line (rows or columns)"
    assert claim_bingo(player, code).json()["status"] == "win"


def test_rule_changes_are_validated(running_game):
    host, game_id, _code = running_game
    with_round = host.get(f"/games/{game_id}/run/state").json()["round"]
    for bad in ({"lines_required": "50"}, {"lines_required": "x"}, {"mode": "bogus"}):
        fields = {"round_id": with_round["id"], "mode": "lines", "lines_required": "1", "rows": "on"}
        fields.update(bad)
        assert host_post(host, game_id, "rules", **fields).status_code == 409
    assert host_post(host, game_id, "rules", round_id=with_round["id"], mode="lines", lines_required="1").status_code == 409  # no line types
    assert host_post(host, game_id, "rules", round_id=99999, mode="lines", lines_required="1", rows="on").status_code == 404


def test_progressive_rounds(app, running_game):
    host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Two Timers")
    _team, cells = team_ticket(app, game_id, "Two Timers")

    # Round 1 (one row): play row 1 and win.
    set_play_order(app, game_id, cells[0:3])
    for _ in range(3):
        host_post(host, game_id, "next")
    assert claim_bingo(player, code).json()["status"] == "win"

    # No further round yet; the host adds a full-house round, then moves on.
    assert host_post(host, game_id, "round", number=2).status_code == 409
    added = host_post(host, game_id, "rounds", name="Full house", mode="full_house", lines_required="1")
    assert added.status_code == 200 and len(added.json()["rounds"]) == 2
    moved = host_post(host, game_id, "round", number=2)
    assert moved.json()["round"]["text"] == "Full house (every square)"

    # The same team may win again in a new round, but now needs the whole ticket.
    assert claim_bingo(player, code).json()["status"] == "rejected"
    age_claims(app)
    set_play_order(app, game_id, cells)
    set_played_count(app, game_id, 9)
    assert claim_bingo(player, code).json()["status"] == "win"
    winners = host.get(f"/games/{game_id}/run/state").json()["winners"]
    assert [w["round"] for w in winners] == [1, 2]


def test_played_rounds_cannot_be_deleted_once_the_game_has_started(app, running_game):
    host, game_id, _code = running_game
    with Session(app.state.engine) as session:
        round_id = session.exec(select(Round.id).where(Round.game_id == game_id)).first()
    host.post(f"/games/{game_id}/rounds/{round_id}/delete",
              data={"csrf_token": csrf_token(host, f"/games/{game_id}")}, follow_redirects=False)
    with Session(app.state.engine) as session:
        assert session.exec(select(Round).where(Round.game_id == game_id)).all()


def test_finishing_stops_play_and_claims(app, running_game):
    host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Last Orders")
    assert host_post(host, game_id, "finish").json()["game"]["status"] == "finished"
    assert host_post(host, game_id, "next").status_code == 409
    assert claim_bingo(player, code).status_code == 409


def test_checking_a_printed_ticket(app, running_game):
    host, game_id, _code = running_game
    from app.models import Ticket
    with Session(app.state.engine) as session:
        ticket = session.exec(select(Ticket).where(Ticket.game_id == game_id, Ticket.number == 1)).one()
        cells = list(ticket.cells)
    set_play_order(app, game_id, cells[3:6])  # row 2 of ticket 1
    for _ in range(2):
        host_post(host, game_id, "next")
    short = host_post(host, game_id, "check", ticket_number=1).json()
    assert short["status"] == "rejected" and short["squares_needed"] == 1 and len(short["missing"]) == 1
    host_post(host, game_id, "next")
    win = host_post(host, game_id, "check", ticket_number=1).json()
    assert win["status"] == "win" and win["lines"] == ["row 2"]
    assert host_post(host, game_id, "check", ticket_number=99).status_code == 404


def test_state_endpoint_describes_the_game(app, running_game):
    host, game_id, code = running_game
    state = host.get(f"/games/{game_id}/run/state").json()
    assert state["game"]["code"] == code and state["join_url"].endswith(f"/join/{code}")
    assert state["total_songs"] == 12 and state["songs_played"] == 0 and state["teams"] == []
    assert len(state["rounds"]) == 1 and state["current_song"] is None
    assert len(pool_ids(app, game_id)) == 12


def test_database_from_phase_2_gains_the_current_round_column(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE game (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO game (name) VALUES ('Old game')"))
    apply_additive_migrations(engine)
    apply_additive_migrations(engine)  # safe to repeat
    assert "current_round" in {c["name"] for c in inspect(engine).get_columns("game")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_round FROM game")).scalar() == 1
