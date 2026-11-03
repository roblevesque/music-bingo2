"""Play order for a running game. Pure Python.

A game stores one shuffled `order` of song ids and an `index` = how many have been
played. The played songs are always `order[:index]`; the rest are still to come.
"""

import random


class PlaylistExhausted(Exception):
    """Every song has been played."""


def new_play_order(pool: list[int], rng: random.Random | None = None) -> list[int]:
    order = list(dict.fromkeys(pool))
    (rng or random.Random()).shuffle(order)
    return order


def played_ids(order: list[int], index: int) -> list[int]:
    return list(order[:index])


def advance(order: list[int], index: int) -> tuple[int, int]:
    """Play the next song. Returns (song_id, new_index)."""
    if index >= len(order):
        raise PlaylistExhausted()
    return order[index], index + 1


def skip_next(order: list[int], index: int) -> list[int]:
    """Move the next song to the end of the order, so it is heard last instead."""
    if len(order) - index < 2:
        raise ValueError("There is no other song to skip to.")
    new_order = list(order)
    new_order.append(new_order.pop(index))
    return new_order


def reshuffle_remaining(order: list[int], index: int, rng: random.Random | None = None) -> list[int]:
    """Reshuffle only the songs not yet played; the played prefix never changes."""
    tail = list(order[index:])
    (rng or random.Random()).shuffle(tail)
    return list(order[:index]) + tail
