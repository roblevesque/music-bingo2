import pytest

from app.services.remote import (
    CODE_ALPHABET, CODE_LENGTH, AttemptLimiter, new_code, normalize_code, remote_view, validate_command,
)

EFFECTS = ("thinking", "win", "lose")


def test_codes_are_short_unambiguous_and_varied():
    codes = {new_code() for _ in range(300)}
    assert len(codes) == 300
    assert all(len(c) == CODE_LENGTH and set(c) <= set(CODE_ALPHABET) for c in codes)
    assert not set("".join(codes)) & set("01OI")


def test_typed_codes_are_forgiven():
    assert normalize_code(" ab-c 23 ") == "ABC23" and normalize_code("") == ""


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def test_the_limiter_blocks_after_too_many_wrong_guesses_then_recovers():
    clock = Clock()
    limiter = AttemptLimiter(max_attempts=3, window_seconds=60, clock=clock)
    for _ in range(2):
        limiter.record_failure("1.2.3.4")
    assert not limiter.blocked("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.blocked("1.2.3.4") and not limiter.blocked("5.6.7.8")  # per client
    clock.now += 61
    assert not limiter.blocked("1.2.3.4")  # old attempts age out
    assert limiter._failures == {}  # and nothing is kept for them


def test_the_window_slides_and_a_success_clears_the_slate():
    clock = Clock()
    limiter = AttemptLimiter(max_attempts=2, window_seconds=10, clock=clock)
    limiter.record_failure("a"); clock.now += 6
    limiter.record_failure("a")
    assert limiter.blocked("a")
    clock.now += 5  # the first attempt (11 s ago) has aged out, the second has not
    assert not limiter.blocked("a")
    limiter.record_failure("a")
    assert limiter.blocked("a")
    limiter.reset("a")
    assert not limiter.blocked("a")


@pytest.mark.parametrize("action", ["next", "replay", "pause", "skip", "start", "next_round", "stop_effect"])
def test_simple_commands_pass_through(action):
    assert validate_command(action, effect_ids=EFFECTS) == {"action": action}


def test_commands_carry_only_what_they_need():
    assert validate_command("next", expect="7") == {"action": "next", "expect": 7}
    assert validate_command("next", expect="0") == {"action": "next", "expect": 0}
    assert validate_command("skip", expect_next="42") == {"action": "skip", "expect_next": 42}
    assert validate_command("effect", effect="win", effect_ids=EFFECTS) == {"action": "effect", "effect": "win"}
    # stray fields are dropped rather than relayed
    assert validate_command("pause", effect="win", expect="3", expect_next="4", effect_ids=EFFECTS) == {"action": "pause"}


@pytest.mark.parametrize("args", [
    dict(action="end_game"), dict(action=""), dict(action="effect", effect="airhorn"), dict(action="effect"),
    dict(action="next", expect="-1"), dict(action="next", expect="abc"), dict(action="next", expect="1.5"),
    dict(action="next", expect="999999999"), dict(action="skip", expect_next="x"),
])
def test_bad_commands_are_refused(args):
    with pytest.raises(ValueError):
        validate_command(effect_ids=EFFECTS, **args)


def host_snapshot():
    song = lambda n: {"id": n, "title": f"Song {n}", "artist": "A", "audio_url": f"/library/{n}/audio", "start_ms": 0, "end_ms": None}
    return {
        "game": {"id": 1, "name": "Pub Night", "code": "JOINME", "status": "active", "grid_size": 5},
        "join_url": "http://x/join/JOINME", "remote": {"enabled": True, "code": "SECRET", "url": "http://x/remote", "connected": 1},
        "round": {"id": 1, "number": 1, "name": "Round 1", "text": "1 line (rows)"},
        "rounds": [{"number": 1}, {"number": 2}], "songs_played": 3, "total_songs": 40,
        "current_song": song(3), "next_song": song(4),
        "played": [song(3)], "upcoming": [song(4), song(5)], "teams": [{"id": 1, "name": "Quiz Kings", "ticket": 3}],
        "claims": [{"id": 2, "team": "B", "ticket": 9, "status": "win", "songs_played": 3, "detail": "row 2"},
                   {"id": 1, "team": "A", "ticket": 3, "status": "win", "songs_played": 3, "detail": "row 1"},
                   {"id": 3, "team": "C", "ticket": 5, "status": "rejected", "songs_played": 2, "detail": "2 short"}],
        "winners": [], "effects": [{"id": "win", "label": "Win", "url": "/static/effects/win.wav", "loop": False}],
    }


def test_the_phone_view_has_what_a_remote_needs_and_nothing_more():
    view = remote_view(host_snapshot(), console_online=True)
    assert view["name"] == "Pub Night" and view["status"] == "active" and view["console_online"] is True
    assert view["current"] == {"title": "Song 3", "artist": "A"} and view["next"]["id"] == 4
    assert view["round"] == {"number": 1, "name": "Round 1", "text": "1 line (rows)"} and view["has_next_round"] is True
    assert [w["team"] for w in view["wins"]] == ["A", "B"]  # valid claims only, oldest first (the tie reads in order)
    assert view["effects"] == [{"id": "win", "label": "Win", "loop": False}]  # no file URLs: the console plays them
    flat = str(view)
    for secret in ("SECRET", "JOINME", "Quiz Kings", "upcoming", "audio_url"):
        assert secret not in flat, f"{secret} leaked to the phone"


def test_the_phone_view_copes_with_the_ends_of_a_game():
    before = host_snapshot() | {"game": {"name": "G", "status": "draft"}, "current_song": None, "songs_played": 0, "claims": []}
    view = remote_view(before, console_online=False)
    assert view["current"] is None and view["wins"] == [] and view["console_online"] is False and view["status"] == "draft"
    last = host_snapshot() | {"next_song": None, "rounds": [{"number": 1}]}
    view = remote_view(last, console_online=True)
    assert view["next"] is None and view["has_next_round"] is False
    assert remote_view(host_snapshot() | {"round": None}, True)["round"] is None
