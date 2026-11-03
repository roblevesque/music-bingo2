"""What counts as a win in a round, on an N x N ticket. Pure Python, no framework.

Cells are numbered row-major: on a 5x5 ticket, row 2 column 3 is position 2*5+3 = 13.
The host chooses the rules per round and may change them as the game goes on, so
rules are plain data that the checker takes as an argument.
"""

from dataclasses import dataclass

MODE_LINES = "lines"
MODE_FULL_HOUSE = "full_house"
MODES = (MODE_LINES, MODE_FULL_HOUSE)


@dataclass(frozen=True)
class RoundRules:
    mode: str = MODE_LINES
    lines_required: int = 1  # how many complete lines win (lines mode only)
    rows: bool = True
    columns: bool = False
    diagonals: bool = False


@dataclass(frozen=True)
class Line:
    kind: str  # "row" | "column" | "diagonal"
    index: int  # row or column number; diagonals: 0 = top-left to bottom-right, 1 = the other
    cells: tuple[int, ...]


def all_lines(size: int, *, rows: bool, columns: bool, diagonals: bool) -> list[Line]:
    lines: list[Line] = []
    if rows:
        for r in range(size):
            lines.append(Line("row", r, tuple(r * size + c for c in range(size))))
    if columns:
        for c in range(size):
            lines.append(Line("column", c, tuple(r * size + c for r in range(size))))
    if diagonals:
        lines.append(Line("diagonal", 0, tuple(i * size + i for i in range(size))))
        lines.append(Line("diagonal", 1, tuple(i * size + (size - 1 - i) for i in range(size))))
    return lines


def enabled_lines(size: int, rules: RoundRules) -> list[Line]:
    return all_lines(size, rows=rules.rows, columns=rules.columns, diagonals=rules.diagonals)


def validate_rules(rules: RoundRules, size: int) -> list[str]:
    """Human-readable problems with these rules for a ticket of this size (empty = fine)."""
    if rules.mode not in MODES:
        return ["Unknown pattern type."]
    if rules.mode == MODE_FULL_HOUSE:
        return []
    available = len(enabled_lines(size, rules))
    if available == 0:
        return ["Choose at least one of rows, columns or diagonals."]
    if not 1 <= rules.lines_required <= available:
        return [f"Lines required must be between 1 and {available} for the chosen line types."]
    return []


def _join_or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def describe_rules(rules: RoundRules, size: int) -> str:
    if rules.mode == MODE_FULL_HOUSE:
        return "Full house (every square)"
    kinds = [
        name
        for name, enabled in (("rows", rules.rows), ("columns", rules.columns), ("diagonals", rules.diagonals))
        if enabled
    ]
    count = rules.lines_required
    return f"{count} line{'' if count == 1 else 's'} ({_join_or(kinds) if kinds else 'none'})"


def describe_line(line: Line) -> str:
    """'row 2', 'column 4', 'diagonal (top-left to bottom-right)' for showing to the host."""
    if line.kind == "diagonal":
        return "diagonal (top-left to bottom-right)" if line.index == 0 else "diagonal (top-right to bottom-left)"
    return f"{line.kind} {line.index + 1}"
