from types import SimpleNamespace as G

from app.services.series import latest_runs, series_key


def test_a_game_that_was_never_rerun_is_its_own_series():
    game = G(id=7, series_id=None, run_number=1)
    assert series_key(game) == 7
    assert latest_runs([game]) == ([game], {7: 1})


def test_only_the_latest_run_of_each_series_is_listed():
    first = G(id=1, series_id=None, run_number=1)
    second = G(id=5, series_id=1, run_number=2)
    third = G(id=9, series_id=1, run_number=3)
    other = G(id=3, series_id=None, run_number=1)
    shown, counts = latest_runs([third, other, second, first])  # newest first, as the list query returns
    assert shown == [third, other]  # input order kept
    assert counts == {9: 3, 3: 1}


def test_deleting_the_newest_run_brings_the_previous_one_back():
    first = G(id=1, series_id=None, run_number=1)
    second = G(id=5, series_id=1, run_number=2)
    assert latest_runs([second, first])[0] == [second]
    assert latest_runs([first])[0] == [first]


def test_runs_stay_grouped_after_the_first_run_is_deleted():
    second = G(id=5, series_id=1, run_number=2)
    third = G(id=9, series_id=1, run_number=3)
    shown, counts = latest_runs([third, second])
    assert shown == [third] and counts == {9: 2}
