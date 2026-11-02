import pytest

from app.services.patterns import (
    MODE_FULL_HOUSE,
    RoundRules,
    all_lines,
    describe_rules,
    enabled_lines,
    validate_rules,
)


def test_line_counts_and_cells_for_5x5():
    lines = all_lines(5, rows=True, columns=True, diagonals=True)
    assert len(lines) == 12  # 5 rows + 5 columns + 2 diagonals
    by_key = {(line.kind, line.index): line.cells for line in lines}
    assert by_key[("row", 1)] == (5, 6, 7, 8, 9)
    assert by_key[("column", 2)] == (2, 7, 12, 17, 22)
    assert by_key[("diagonal", 0)] == (0, 6, 12, 18, 24)
    assert by_key[("diagonal", 1)] == (4, 8, 12, 16, 20)


def test_only_enabled_directions_are_returned():
    assert len(enabled_lines(4, RoundRules(rows=True, columns=False, diagonals=False))) == 4
    assert len(enabled_lines(4, RoundRules(rows=False, columns=False, diagonals=True))) == 2


@pytest.mark.parametrize(
    "rules, ok",
    [
        (RoundRules(), True),
        (RoundRules(lines_required=5), True),  # five rows on a 5x5
        (RoundRules(lines_required=6), False),  # only five rows exist
        (RoundRules(lines_required=0), False),
        (RoundRules(lines_required=12, rows=True, columns=True, diagonals=True), True),
        (RoundRules(rows=False), False),  # no directions at all
        (RoundRules(mode=MODE_FULL_HOUSE, rows=False), True),  # directions irrelevant
        (RoundRules(mode="bogus"), False),
    ],
)
def test_validate_rules(rules, ok):
    assert (validate_rules(rules, 5) == []) is ok


def test_describe_rules():
    assert describe_rules(RoundRules(), 5) == "1 line (rows)"
    assert describe_rules(RoundRules(lines_required=2, columns=True), 5) == "2 lines (rows or columns)"
    assert (
        describe_rules(RoundRules(lines_required=1, columns=True, diagonals=True), 5)
        == "1 line (rows, columns or diagonals)"
    )
    assert describe_rules(RoundRules(mode=MODE_FULL_HOUSE), 5) == "Full house (every square)"
