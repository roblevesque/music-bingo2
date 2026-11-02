"""Ticket generation: unique, balanced N x N tickets from a song pool. Pure Python."""

import math
import random
from dataclasses import dataclass

ATTEMPTS_PER_LEVEL = 30  # tries at each "how different must tickets be" level before relaxing
ATTEMPTS_AT_FLOOR = 2000  # tries to find any not-yet-used set once relaxed as far as possible


class TicketGenerationError(ValueError):
    """The request can't be satisfied; the message is safe to show to the host."""


class PoolTooSmall(TicketGenerationError):
    pass


class TooManyTickets(TicketGenerationError):
    pass


@dataclass(frozen=True)
class GeneratedTickets:
    tickets: list[list[int]]  # each is size*size song ids, row-major
    min_difference: int  # any two tickets differ by at least this many songs


def default_target_difference(pool_size: int, size: int) -> int:
    cells = size * size
    return max(1, min(cells // 5, pool_size - cells))


def generate_tickets(
    pool: list[int],
    size: int,
    count: int,
    rng: random.Random | None = None,
    target_difference: int | None = None,
) -> GeneratedTickets:
    """Make `count` tickets of size x size songs from `pool`.

    - No ticket repeats another's set of songs.
    - Songs are used about equally often across tickets.
    - Tickets are kept at least `target_difference` songs apart where the pool allows,
      relaxing step by step (never below 1, i.e. merely distinct) when it doesn't.
    """
    if size < 2:
        raise ValueError("grid size must be at least 2")
    if count < 1:
        raise ValueError("ticket count must be at least 1")
    songs = list(dict.fromkeys(pool))  # de-duplicate, keep order
    cells = size * size
    if len(songs) < cells:
        raise PoolTooSmall(
            f"A {size}x{size} ticket needs {cells} songs, but only {len(songs)} were selected."
        )
    if math.comb(len(songs), cells) < count:
        raise TooManyTickets(
            f"Only {math.comb(len(songs), cells)} different tickets are possible from "
            f"{len(songs)} songs. Select more songs or ask for fewer tickets."
        )

    rng = rng or random.Random()
    usage = [0] * len(songs)
    masks: list[int] = []
    tickets: list[list[int]] = []
    level = default_target_difference(len(songs), size) if target_difference is None else max(1, target_difference)

    for _ in range(count):
        chosen = None
        while chosen is None:
            attempts = ATTEMPTS_AT_FLOOR if level == 1 else ATTEMPTS_PER_LEVEL
            for attempt in range(attempts):
                jitter = 1.0 + attempt / 10  # widen the random spread if we keep colliding
                picked = sorted(range(len(songs)), key=lambda i: usage[i] + rng.random() * jitter)[:cells]
                mask = 0
                for i in picked:
                    mask |= 1 << i
                if all(cells - (mask & other).bit_count() >= level for other in masks):
                    chosen = picked
                    masks.append(mask)
                    break
            else:
                if level == 1:
                    raise TooManyTickets(
                        "Could not find enough different tickets. Select more songs or ask for fewer tickets."
                    )
                level -= 1
        for i in chosen:
            usage[i] += 1
        grid = [songs[i] for i in chosen]
        rng.shuffle(grid)
        tickets.append(grid)

    return GeneratedTickets(tickets=tickets, min_difference=level)
