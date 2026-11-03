from sqlmodel import Session, select

from app.models import Claim, Team
from app.services.snapshots import public_state
from tests.conftest import (
    age_claims, claim_bingo, create_game, csrf_token, game_id_from, get_game, host_post,
    join_game, new_player, seed_songs, set_play_order, team_ticket,
)


def test_home_page_offers_joining_to_visitors(app, client):
    from tests.conftest import add_user
    add_user(app)
    page = client.get("/")
    assert page.status_code == 200 and "Join a game" in page.text and "Host log in" in page.text


def test_joining_assigns_different_tickets_and_resumes_in_the_same_browser(app, running_game):
    _host, game_id, code = running_game
    a, b = new_player(app), new_player(app)
    first = join_game(a, code, "Quiz Kings")
    assert first.status_code == 303 and first.headers["location"] == f"/play/{code}"
    join_game(b, code, "The Beatles Tribute")
    again = join_game(a, code, "Anything else")  # same browser: resumes, no second team
    assert again.headers["location"] == f"/play/{code}"
    with Session(app.state.engine) as session:
        teams = session.exec(select(Team).where(Team.game_id == game_id)).all()
    assert len(teams) == 2 and len({t.ticket_id for t in teams}) == 2
    assert "Quiz Kings" in a.get(f"/play/{code}").text


def test_join_validation(app, running_game):
    _host, _game_id, code = running_game
    assert join_game(new_player(app), "ZZZZZZ").status_code == 404
    assert join_game(new_player(app), code, "x").status_code == 400  # too short
    assert join_game(new_player(app), code.lower(), "Lower Case Code").status_code == 303
    assert join_game(new_player(app), f" {code[:3]}-{code[3:]} ", "Spaced Code").status_code == 303
    taken = join_game(new_player(app), code, "  lower   CASE code ")
    assert taken.status_code == 400 and "already taken" in taken.text


def test_cannot_join_when_every_ticket_is_taken(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3, tickets=2))
    code = get_game(app, game_id).code
    assert join_game(new_player(app), code, "One").status_code == 303
    assert join_game(new_player(app), code, "Two").status_code == 303
    full = join_game(new_player(app), code, "Three")
    assert full.status_code == 400 and "taken" in full.text


def test_cannot_join_a_finished_game(app, running_game):
    host, game_id, code = running_game
    host_post(host, game_id, "finish")
    response = join_game(new_player(app), code, "Latecomers")
    assert response.status_code == 400 and "finished" in response.text


def test_play_page_needs_a_team(app, running_game):
    _host, _game_id, code = running_game
    stranger = new_player(app)
    response = stranger.get(f"/play/{code}", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/join/{code}"
    assert stranger.get("/play/ZZZZZZ").status_code == 404


def test_marks_are_saved_and_shown_again(app, running_game):
    _host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Markers")
    token = csrf_token(player, f"/play/{code}")
    for position, marked in ((0, "true"), (4, "true"), (0, "false")):
        response = player.post(f"/play/{code}/mark", data={"position": position, "marked": marked, "csrf_token": token})
        assert response.status_code == 200
    assert team_ticket(app, game_id, "Markers")[0].marks == [4]
    assert player.post(f"/play/{code}/mark", data={"position": 9, "marked": "true", "csrf_token": token}).status_code == 400
    assert player.post(f"/play/{code}/mark", data={"position": 1, "marked": "true"}).status_code == 403  # no CSRF token
    assert new_player(app).post(f"/play/{code}/mark", data={"position": 1, "csrf_token": token}).status_code == 403


def test_full_claim_flow(app, running_game):
    host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Winners")
    _team, cells = team_ticket(app, game_id, "Winners")

    # Nothing played yet: a claim is rejected, and a second one right away is held back.
    assert claim_bingo(player, code).json()["status"] == "rejected"
    assert claim_bingo(player, code).status_code == 429

    # Play exactly the first row of this team's ticket.
    set_play_order(app, game_id, cells[0:3])
    for _ in range(3):
        assert host_post(host, game_id, "next").status_code == 200
    age_claims(app)
    won = claim_bingo(player, code)
    assert won.json()["status"] == "win"
    assert claim_bingo(player, code).json()["status"] == "already_claimed"

    with Session(app.state.engine) as session:
        claims = session.exec(select(Claim).order_by(Claim.id)).all()
    assert [c.status for c in claims] == ["rejected", "win"]
    assert claims[1].songs_played == 3 and "row 1" in claims[1].detail

    state = host.get(f"/games/{game_id}/run/state").json()
    assert state["winners"] == [{"round": 1, "round_name": "Round 1", "teams": ["Winners"]}]
    assert state["claims"][0]["status"] == "win"


def test_claims_need_a_running_game(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3))
    code = get_game(app, game_id).code
    player = new_player(app)
    join_game(player, code, "Early Birds")  # joining the lobby before the start is fine
    assert claim_bingo(player, code).status_code == 409


def test_players_snapshot_never_reveals_songs(app, running_game):
    host, game_id, code = running_game
    host_post(host, game_id, "next")
    with Session(app.state.engine) as session:
        snapshot = public_state(session, get_game(app, game_id))
    assert set(snapshot) == {"status", "round", "songs_played", "total_songs", "winners"}
    assert snapshot["songs_played"] == 1 and "title" not in str(snapshot)


def test_event_streams_refuse_strangers(app, running_game):
    host, game_id, code = running_game
    assert new_player(app).get(f"/play/{code}/events").status_code == 403
    assert new_player(app).get("/play/ZZZZZZ/events").status_code == 404
    assert new_player(app).get(f"/games/{game_id}/run/events", follow_redirects=False).status_code == 303
