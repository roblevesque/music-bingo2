import math
import random
from collections import Counter

import pytest

from app.services.ticket_gen import PoolTooSmall, TooManyTickets, generate_tickets


def rng(seed=1234):
    return random.Random(seed)


def test_tickets_have_the_right_shape_and_only_pool_songs():
    pool = list(range(1, 41))
    result = generate_tickets(pool, 5, 20, rng())
    assert len(result.tickets) == 20
    for ticket in result.tickets:
        assert len(ticket) == 25
        assert len(set(ticket)) == 25  # no song twice on one ticket
        assert set(ticket) <= set(pool)


def test_no_two_tickets_have_the_same_songs():
    result = generate_tickets(list(range(1, 31)), 5, 60, rng())
    sets = {frozenset(t) for t in result.tickets}
    assert len(sets) == 60


def test_songs_are_used_about_equally_often():
    result = generate_tickets(list(range(1, 51)), 5, 80, rng())
    usage = Counter(song for ticket in result.tickets for song in ticket)
    assert len(usage) == 50  # every song appears somewhere
    assert max(usage.values()) - min(usage.values()) <= 4


def test_reported_min_difference_is_a_true_guarantee():
    result = generate_tickets(list(range(1, 61)), 5, 40, rng())
    sets = [set(t) for t in result.tickets]
    smallest = min(25 - len(a & b) for i, a in enumerate(sets) for b in sets[i + 1:])
    assert smallest >= result.min_difference >= 1


def test_big_pool_keeps_tickets_well_apart():
    result = generate_tickets(list(range(1, 76)), 5, 30, rng())
    assert result.min_difference >= 5  # the default target for a roomy pool


def test_tight_pool_relaxes_but_stays_distinct():
    result = generate_tickets(list(range(1, 28)), 5, 40, rng())  # 27 songs, 25 per ticket
    assert len({frozenset(t) for t in result.tickets}) == 40
    assert result.min_difference >= 1


def test_arrangement_is_shuffled():
    result = generate_tickets(list(range(1, 41)), 5, 10, rng())
    assert any(t != sorted(t) for t in result.tickets)


def test_same_seed_gives_same_tickets():
    a = generate_tickets(list(range(1, 41)), 5, 10, rng(7))
    b = generate_tickets(list(range(1, 41)), 5, 10, rng(7))
    assert a.tickets == b.tickets


def test_other_grid_sizes():
    assert all(len(t) == 9 for t in generate_tickets(list(range(1, 20)), 3, 10, rng()).tickets)
    assert all(len(t) == 16 for t in generate_tickets(list(range(1, 30)), 4, 10, rng()).tickets)


def test_pool_must_cover_one_ticket():
    with pytest.raises(PoolTooSmall):
        generate_tickets(list(range(1, 25)), 5, 1, rng())


def test_cannot_ask_for_more_tickets_than_exist():
    with pytest.raises(TooManyTickets):
        generate_tickets(list(range(1, 11)), 3, math.comb(10, 9) + 1, rng())


def test_asking_for_every_possible_ticket_still_terminates():
    pool = list(range(1, 11))  # C(10, 9) = 10 possible tickets
    result = generate_tickets(pool, 3, 10, rng())
    assert len({frozenset(t) for t in result.tickets}) == 10


def test_duplicate_pool_entries_are_ignored():
    result = generate_tickets([1, 1, 2, 2] + list(range(3, 12)), 3, 2, rng())
    assert all(len(set(t)) == 9 for t in result.tickets)
