"""Claim verification: has this ticket won under this round's rules? Pure Python.

The caller decides which songs count as played (the prefix of the play order up to
the moment of the claim) and which rules apply (the current round's, as set by the host).
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.services.patterns import (
    MODE_FULL_HOUSE,
    Line,
    RoundRules,
    enabled_lines,
    validate_rules,
)

WIN = "win"
REJECTED = "rejected"


@dataclass(frozen=True)
class ClaimResult:
    status: str  # WIN or REJECTED
    completed: tuple[Line, ...]  # lines fully played (lines mode)
    missing_song_ids: tuple[int, ...]  # REJECTED: songs still needed on the closest route
    squares_needed: int  # REJECTED: how many more played songs would give a win

    @property
    def is_win(self) -> bool:
        return self.status == WIN


def verify_claim(
    cells: Sequence[int], played: Collection[int], size: int, rules: RoundRules
) -> ClaimResult:
    """Decide a claim. The win/reject decision is exact; the 'missing' list is a hint."""
    if len(cells) != size * size:
        raise ValueError(f"ticket has {len(cells)} squares, expected {size * size}")
    problems = validate_rules(rules, size)
    if problems:
        raise ValueError(problems[0])

    played_set = set(played)
    unplayed = {pos for pos, song in enumerate(cells) if song not in played_set}

    if rules.mode == MODE_FULL_HOUSE:
        if not unplayed:
            return ClaimResult(WIN, (), (), 0)
        return _rejected((), unplayed, cells)

    lines = enabled_lines(size, rules)
    complete = [line for line in lines if unplayed.isdisjoint(line.cells)]
    if len(complete) >= rules.lines_required:
        return ClaimResult(WIN, tuple(complete), (), 0)

    # Closest route to a win: greedily add the incomplete line that needs the fewest
    # extra squares (squares shared with already-chosen lines are only counted once).
    remaining = [line for line in lines if line not in complete]
    still_needed: set[int] = set()
    for _ in range(rules.lines_required - len(complete)):
        best = min(remaining, key=lambda line: len((unplayed & set(line.cells)) - still_needed))
        remaining.remove(best)
        still_needed |= unplayed & set(best.cells)
    return _rejected(tuple(complete), still_needed, cells)


def _rejected(completed: tuple[Line, ...], needed: set[int], cells: Sequence[int]) -> ClaimResult:
    missing = tuple(cells[pos] for pos in sorted(needed))
    return ClaimResult(REJECTED, completed, missing, len(needed))
