import os
from pathlib import Path

from app.config import DEFAULT_APP_NAME, DEFAULT_TAGLINE, Settings, _app_name, _tagline, load_settings

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_the_tool_is_called_track_bingo_by_default():
    assert DEFAULT_APP_NAME == "Track Bingo" and DEFAULT_TAGLINE == "All aboard!"
    settings = Settings(data_dir=Path("."))
    assert (settings.app_name, settings.tagline) == ("Track Bingo", "All aboard!")


def test_the_name_is_tidied_and_never_blank():
    assert _app_name(None) == "Track Bingo" and _app_name("") == "Track Bingo" and _app_name("   ") == "Track Bingo"
    assert _app_name("  Iron   Rail \n Bingo ") == "Iron Rail Bingo"
    assert len(_app_name("x" * 100)) == 40


def test_the_tagline_can_be_changed_or_hidden():
    assert _tagline(None) == "All aboard!"            # not set: the default
    assert _tagline("") == "" and _tagline("   ") == ""  # set but blank: no tagline
    assert _tagline("  Full   steam ahead! ") == "Full steam ahead!"
    assert len(_tagline("y" * 200)) == 80


def test_both_come_from_the_environment():
    saved = {k: os.environ.get(k) for k in ("MUSICBINGO_APP_NAME", "MUSICBINGO_TAGLINE")}
    try:
        os.environ["MUSICBINGO_APP_NAME"], os.environ["MUSICBINGO_TAGLINE"] = "Iron Rail", "Hop on!"
        settings = load_settings()
        assert (settings.app_name, settings.tagline) == ("Iron Rail", "Hop on!")
        os.environ["MUSICBINGO_APP_NAME"], os.environ["MUSICBINGO_TAGLINE"] = "", ""
        settings = load_settings()
        assert (settings.app_name, settings.tagline) == ("Track Bingo", "")
        del os.environ["MUSICBINGO_APP_NAME"], os.environ["MUSICBINGO_TAGLINE"]
        settings = load_settings()
        assert (settings.app_name, settings.tagline) == ("Track Bingo", "All aboard!")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_no_template_hard_codes_the_name():
    """The name is a setting, so templates must use {{ app_name }} and never spell it out."""
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text()
        for name in ("Music Bingo", "Track Bingo"):
            assert name not in text, f"{path.name} hard-codes {name!r}; use {{{{ app_name }}}}"


def test_the_header_and_page_titles_use_the_setting():
    base = (TEMPLATES / "base.html").read_text()
    assert "{% block title %}{{ app_name }}{% endblock %}" in base and "&#9835; {{ app_name }}" in base
    for name in ("library", "games", "branding", "account", "users", "login", "setup", "join", "error"):
        assert "&middot; {{ app_name }}" in (TEMPLATES / f"{name}.html").read_text(), name
