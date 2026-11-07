import random

from app.services.ticket_gen import generate_tickets, variety_target, variety_warning


def test_target_is_a_fifth_of_the_squares():
    assert [variety_target(n) for n in (3, 4, 5, 6)] == [1, 3, 5, 7]


def test_no_warning_when_tickets_are_varied_enough():
    assert variety_warning(5, 5) is None and variety_warning(9, 5) is None
    assert variety_warning(1, 3) is None  # a 3x3 ticket can't be asked for more than "different"


def test_warning_explains_how_close_the_tickets_are():
    message = variety_warning(2, 5)
    assert "more than 80%" in message and "2 of 25" in message and "aim is 5" in message


def test_small_pools_warn_and_roomy_pools_do_not():
    tight = generate_tickets(list(range(1, 28)), 5, 40, random.Random(1))  # 27 songs for 25 squares
    assert variety_warning(tight.min_difference, 5) is not None
    roomy = generate_tickets(list(range(1, 76)), 5, 30, random.Random(1))
    assert variety_warning(roomy.min_difference, 5) is None
