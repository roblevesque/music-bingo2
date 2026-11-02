import pytest

from app.services.parsing import format_time_ms, normalize_tags, parse_time_ms


@pytest.mark.parametrize(
    "text, expected",
    [("", None), ("  ", None), ("75", 75000), ("75.5", 75500), ("1:15", 75000),
     ("1:15.5", 75500), ("1:02:03", 3723000), ("0", 0)],
)
def test_parse_time_ms(text, expected):
    assert parse_time_ms(text) == expected


@pytest.mark.parametrize("text", ["abc", "-5", "1:-5", "1:2:3:4", "nan", "inf", "1:xx"])
def test_parse_time_ms_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_time_ms(text)


@pytest.mark.parametrize(
    "ms, expected",
    [(None, ""), (0, "0:00.0"), (90000, "1:30.0"), (5500, "0:05.5"), (59960, "1:00.0")],
)
def test_format_time_ms(ms, expected):
    assert format_time_ms(ms) == expected


def test_time_round_trip():
    for ms in (0, 1500, 61000, 125300):
        assert parse_time_ms(format_time_ms(ms)) == ms


def test_normalize_tags():
    assert normalize_tags("Rock, 80s ,rock,, ") == "rock,80s"
    assert normalize_tags("") == ""
    assert len(normalize_tags(",".join(f"t{i}" for i in range(50))).split(",")) == 20
