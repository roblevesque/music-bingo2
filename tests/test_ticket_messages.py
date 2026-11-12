import pytest

from app.services.ticket_gen import TooManyTickets, generate_tickets


def test_one_possible_ticket_is_worded_in_the_singular():
    with pytest.raises(TooManyTickets) as caught:
        generate_tickets(list(range(1, 10)), 3, 2)  # 9 songs fill a 3x3 ticket exactly one way
    assert "Only 1 different ticket is possible from 9 songs" in str(caught.value)


def test_several_possible_tickets_are_worded_in_the_plural():
    with pytest.raises(TooManyTickets) as caught:
        generate_tickets(list(range(1, 11)), 3, 11)  # C(10, 9) = 10 possible
    assert "Only 10 different tickets are possible from 10 songs" in str(caught.value)
