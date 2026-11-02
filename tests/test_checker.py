import pytest

from app.services.checker import REJECTED, WIN, verify_claim
from app.services.patterns import MODE_FULL_HOUSE, RoundRules

SIZE = 3
CELLS = list(range(100, 109))  # song ids 100..108, row-major on a 3x3 ticket
# 100 101 102
# 103 104 105
# 106 107 108


def claim(played, **rules):
    return verify_claim(CELLS, played, SIZE, RoundRules(**rules))


def test_row_wins_by_default():
    result = claim({103, 104, 105})
    assert result.status == WIN and result.is_win
    assert [(line.kind, line.index) for line in result.completed] == [("row", 1)]


def test_column_only_counts_when_enabled():
    column = {101, 104, 107}
    assert claim(column).status == REJECTED  # rows only by default
    assert claim(column, columns=True).status == WIN


def test_diagonals_only_count_when_enabled():
    diagonal = {100, 104, 108}
    assert claim(diagonal, columns=True).status == REJECTED
    assert claim(diagonal, diagonals=True).status == WIN


def test_extra_played_songs_do_not_matter():
    assert claim(set(CELLS) | {1, 2, 3}).status == WIN


def test_two_lines_required():
    one_row = {100, 101, 102}
    assert claim(one_row, lines_required=2).status == REJECTED
    assert claim(one_row | {103, 104, 105}, lines_required=2).status == WIN


def test_crossing_lines_share_a_square_but_count_separately():
    # Row 0 and column 0 share song 100: five songs give two complete lines.
    played = {100, 101, 102, 103, 106}
    assert claim(played, lines_required=2, columns=True).status == WIN
    assert claim(played, lines_required=2).status == REJECTED  # rows only: just one row


def test_full_house_needs_every_song():
    assert claim(set(CELLS) - {108}, mode=MODE_FULL_HOUSE).status == REJECTED
    assert claim(set(CELLS), mode=MODE_FULL_HOUSE).status == WIN


def test_rejection_reports_the_closest_route():
    result = claim({100, 101, 104})  # row 0 is one song short (102)
    assert result.status == REJECTED
    assert result.missing_song_ids == (102,)
    assert result.squares_needed == 1


def test_rejection_counts_shared_squares_once():
    # Rows+columns, two lines needed, nothing played: best route is row 0 + column 0
    # (5 squares, since they share one) rather than two disjoint rows (6 squares).
    result = claim(set(), lines_required=2, columns=True)
    assert result.squares_needed == 5
    assert len(result.missing_song_ids) == 5


def test_claim_with_nothing_played_is_rejected():
    result = claim(set())
    assert result.status == REJECTED and result.completed == ()


def test_wrong_ticket_size_or_bad_rules_raise():
    with pytest.raises(ValueError):
        verify_claim(CELLS[:-1], set(), SIZE, RoundRules())
    with pytest.raises(ValueError):
        verify_claim(CELLS, set(), SIZE, RoundRules(lines_required=99))
