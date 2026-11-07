import re

import pytest

from app.services.pdf import Fonts, build_tickets_pdf, fit_text, printable
from tests.conftest import add_user, create_game, game_id_from, login, new_player, seed_songs


def sheets(count, size=3):
    return [(n, [(f"Song {n}-{i} with a long title", f"Artist {i}") for i in range(size * size)])
            for n in range(1, count + 1)]


def page_count(pdf):
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf))


@pytest.mark.parametrize("per_page, pages", [(1, 5), (2, 3), (4, 2)])
def test_pages_match_tickets_per_page(per_page, pages):
    pdf = build_tickets_pdf("Pub Night", 3, sheets(5), per_page=per_page)
    assert pdf.startswith(b"%PDF") and page_count(pdf) == pages


@pytest.mark.parametrize("paper", ["letter", "a4"])
def test_both_paper_sizes(paper):
    assert build_tickets_pdf("Pub Night", 5, sheets(2, 5), paper=paper).startswith(b"%PDF")


def test_awkward_text_does_not_break_layout():
    odd = [(1, [("\u65e5\u672c\u8a9e \u2013 \u00f1and\u00fa", ""), ("A" * 200, "B" * 200)] + [("t", "a")] * 7)]
    assert build_tickets_pdf("\u00dcn\u00efcode \u65e5\u672c game " * 5, 3, odd).startswith(b"%PDF")
    assert build_tickets_pdf("Big", 9, sheets(2, 9), per_page=4).startswith(b"%PDF")


def test_rejects_bad_requests():
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, [])
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, sheets(1), paper="tabloid")
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, sheets(1), per_page=3)


def test_unsupported_characters_become_question_marks():
    assert printable("\u65e5\u672c \u00f1 \u201cq\u201d", Fonts()) == "?? \u00f1 \u201cq\u201d"
    assert printable("  spaced   out ", Fonts()) == "spaced out"


def test_text_shrinks_to_fit_then_is_cut_with_an_ellipsis():
    size, lines = fit_text("Short", "Helvetica-Bold", 14, 100, 30)
    assert size == 14 and lines == ["Short"]
    size, lines = fit_text("word " * 60, "Helvetica-Bold", 14, 60, 30)
    assert size == 5.0 and len(lines) * size * 1.15 <= 30 and lines[-1].endswith("\u2026")


def test_download_route(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, name="Pub Night!", grid_size=3, tickets=5))
    response = logged_in.get(f"/games/{game_id}/tickets.pdf?paper=a4&per_page=2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Pub-Night-tickets.pdf"'
    assert response.content.startswith(b"%PDF") and page_count(response.content) == 3
    assert logged_in.get(f"/games/{game_id}/tickets.pdf").status_code == 200  # defaults
    assert logged_in.get(f"/games/{game_id}/tickets.pdf?per_page=3").status_code == 400
    assert logged_in.get(f"/games/{game_id}/tickets.pdf?paper=tabloid").status_code == 400
    assert "tickets.pdf" in logged_in.get(f"/games/{game_id}").text


def test_download_needs_the_owning_host(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3))
    assert new_player(app).get(f"/games/{game_id}/tickets.pdf", follow_redirects=False).status_code == 303
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get(f"/games/{game_id}/tickets.pdf").status_code == 404
