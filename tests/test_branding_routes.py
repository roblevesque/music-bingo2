import io

from PIL import Image
from sqlmodel import Session, select

from app.models import Branding
from tests.conftest import (
    add_user, create_game, csrf_token, game_id_from, get_game, join_game, login, new_player, seed_songs,
)


def png(color="red", size=(60, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def save(client, logo=None, **fields):
    data = {"header_text": "", "footer_text": "", "csrf_token": csrf_token(client, "/branding")}
    data.update(fields)
    files = {"logo": logo} if logo else None
    return client.post("/branding", data=data, files=files, follow_redirects=False)


def row(app, user_id=1):
    with Session(app.state.engine) as session:
        return session.exec(select(Branding).where(Branding.owner_id == user_id)).first()


def logo_files(app):
    return sorted(p.name for p in app.state.settings.branding_dir.iterdir())


def test_branding_needs_a_host_login(client):
    for path in ("/branding", "/branding/logo", "/branding/preview.pdf"):
        assert client.get(path, follow_redirects=False).status_code == 303


def test_text_and_colour_are_saved_and_shown_again(app, logged_in):
    response = save(logged_in, header_text="  Thursday   Music Bingo ", footer_text="The Rusty Anchor",
                    use_accent="on", accent_color="#2A9D8F")
    assert response.status_code == 303
    saved = row(app)
    assert (saved.header_text, saved.footer_text, saved.accent_color) == ("Thursday Music Bingo", "The Rusty Anchor", "#2a9d8f")
    page = logged_in.get("/branding").text
    assert "Thursday Music Bingo" in page and "The Rusty Anchor" in page and 'value="#2a9d8f"' in page


def test_accent_can_be_switched_off_again(app, logged_in):
    save(logged_in, use_accent="on", accent_color="#2a9d8f")
    save(logged_in, accent_color="#2a9d8f")  # the box is no longer ticked
    assert row(app).accent_color == ""


def test_invalid_input_is_refused_and_nothing_is_saved(app, logged_in):
    assert save(logged_in, use_accent="on", accent_color="teal").status_code == 400
    assert save(logged_in, header_text="x" * 81).status_code == 400
    assert save(logged_in, footer_text="x" * 121).status_code == 400
    assert row(app) is None


def test_logo_upload_replace_and_remove(app, logged_in):
    assert save(logged_in, logo=("logo.png", png("red"), "image/png")).status_code == 303
    first = logo_files(app)
    assert len(first) == 1 and first[0].endswith(".png")
    served = logged_in.get("/branding/logo")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"

    save(logged_in, logo=("other.png", png("blue"), "image/png"))
    second = logo_files(app)
    assert len(second) == 1 and second != first  # the old file was cleaned up

    save(logged_in, remove_logo="on")
    assert logo_files(app) == [] and row(app).logo_filename == ""
    assert logged_in.get("/branding/logo").status_code == 404


def test_bad_logos_are_refused(app, logged_in):
    assert save(logged_in, logo=("notes.txt", b"hello", "text/plain")).status_code == 400
    assert save(logged_in, logo=("fake.png", b"not really a png", "image/png")).status_code == 400
    too_big = png(size=(1500, 1500)) + b"\0" * (1024 * 1024)
    assert save(logged_in, logo=("big.png", too_big, "image/png")).status_code == 400
    assert logo_files(app) == []


def test_a_logo_belongs_to_its_host(app, logged_in):
    save(logged_in, logo=("logo.png", png(), "image/png"))
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get("/branding/logo").status_code == 404


def test_players_see_the_accent_and_logo_only_when_branded(app, running_game):
    host, game_id, code = running_game
    player = new_player(app)
    join_game(player, code, "Branded Team")
    plain = player.get(f"/play/{code}").text
    assert "brand-logo" not in plain and "--accent:" not in plain

    save(host, logo=("logo.png", png(), "image/png"), use_accent="on", accent_color="#102030")
    branded = player.get(f"/play/{code}").text
    assert "--accent: #102030" in branded and "--accent-text: #ffffff" in branded
    assert f'src="/brand/{code}/logo?v=logo-' in branded
    served = new_player(app).get(f"/brand/{code.lower()}/logo")  # public, and the code is forgiving
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert new_player(app).get("/brand/ZZZZZZ/logo").status_code == 404


def test_public_logo_404s_when_the_host_has_none(app, running_game):
    _host, _game_id, code = running_game
    assert new_player(app).get(f"/brand/{code}/logo").status_code == 404


def test_tickets_pdf_uses_the_branding(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3, tickets=4))
    plain = logged_in.get(f"/games/{game_id}/tickets.pdf")
    save(logged_in, logo=("logo.png", png(size=(300, 100)), "image/png"), header_text="Branded", footer_text="Footer",
         use_accent="on", accent_color="#2a9d8f")
    branded = logged_in.get(f"/games/{game_id}/tickets.pdf")
    assert plain.status_code == branded.status_code == 200
    assert branded.content.startswith(b"%PDF") and branded.content != plain.content and len(branded.content) > len(plain.content)
    assert "branded" in logged_in.get(f"/games/{game_id}/tickets/1").text


def test_preview_pdf(app, logged_in):
    response = logged_in.get("/branding/preview.pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert logged_in.get("/branding/preview.pdf?paper=a4").status_code == 200
    assert logged_in.get("/branding/preview.pdf?paper=tabloid").status_code == 400
