import random

import pytest

from app.services.playlist import (
    PlaylistExhausted, advance, new_play_order, played_ids, reshuffle_remaining, skip_next,
)


def test_new_play_order_is_a_shuffled_copy_without_duplicates():
    pool = list(range(1, 31))
    order = new_play_order(pool + [1, 2], random.Random(1))
    assert sorted(order) == pool and order != pool


def test_advance_walks_the_order_and_then_runs_out():
    order = [10, 20, 30]
    song, index = advance(order, 0)
    assert (song, index) == (10, 1)
    assert played_ids(order, index) == [10]
    song, index = advance(order, 2)
    assert (song, index) == (30, 3)
    with pytest.raises(PlaylistExhausted):
        advance(order, 3)


def test_skip_moves_the_next_song_to_the_end_and_keeps_played_songs():
    assert skip_next([1, 2, 3, 4], 1) == [1, 3, 4, 2]
    with pytest.raises(ValueError):
        skip_next([1, 2, 3], 2)  # only one song left


def test_reshuffle_never_touches_the_played_prefix():
    order = list(range(1, 21))
    for seed in range(5):
        result = reshuffle_remaining(order, 6, random.Random(seed))
        assert result[:6] == order[:6]
        assert sorted(result[6:]) == order[6:]
    assert reshuffle_remaining(order, 6, random.Random(0)) != order  # actually shuffles
