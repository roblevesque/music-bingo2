"""Runs of the same game. Pure Python.

"Run again" creates a new Game row (new join code, teams and claims) in the same
series as the one it was copied from. Only the latest run of each series is listed,
so re-running a game never adds clutter; earlier runs are history on the game page.
"""

from collections.abc import Iterable, Sequence


def series_key(game) -> int:
    """Games that were never re-run have no series_id and form a series of their own."""
    return game.series_id or game.id


def latest_runs(games: Iterable) -> tuple[list, dict[int, int]]:
    """Returns (the latest run of each series, in the input order; game id -> runs in its series)."""
    games = list(games)
    newest: dict[int, object] = {}
    counts: dict[int, int] = {}
    for game in games:
        key = series_key(game)
        counts[key] = counts.get(key, 0) + 1
        if key not in newest or game.run_number > newest[key].run_number:
            newest[key] = game
    shown = [game for game in games if newest[series_key(game)] is game]
    return shown, {game.id: counts[series_key(game)] for game in shown}
