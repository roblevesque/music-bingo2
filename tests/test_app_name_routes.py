from tests.conftest import add_user


def test_pages_show_track_bingo_by_default(app, client):
    add_user(app)
    html = client.get("/").text  # the landing page, since a host exists
    assert "<title>Track Bingo</title>" in html and "&#9835; Track Bingo</a>" in html
    assert "All aboard!" in html and "Music Bingo" not in html


def test_a_different_name_and_tagline_apply_everywhere(app, client):
    add_user(app)
    object.__setattr__(app.state.settings, "app_name", "Iron Rail")
    object.__setattr__(app.state.settings, "tagline", "Hop on!")
    html = client.get("/").text
    assert "<title>Iron Rail</title>" in html and "&#9835; Iron Rail</a>" in html and "Hop on!" in html
    assert "Track Bingo" not in html
    assert "&middot; Iron Rail</title>" in client.get("/login").text
    assert "Iron Rail" in client.get("/no/such/page", headers={"Accept": "text/html"}).text  # error pages too


def test_an_empty_tagline_is_hidden(app, client):
    add_user(app)
    object.__setattr__(app.state.settings, "tagline", "")
    assert 'class="tagline"' not in client.get("/").text


def test_every_host_page_title_carries_the_name(logged_in):
    for path in ("/library", "/games", "/branding", "/account", "/users"):
        assert "&middot; Track Bingo</title>" in logged_in.get(path).text, path
