import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_templates_never_build_absolute_urls():
    """`url_for` makes absolute URLs from the request's Host header, which breaks behind a proxy (see web.static_url)."""
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text()
        assert "url_for(" not in text, f"{path.name} uses url_for; use static_url or a plain path"
        assert not re.search(r'(?:src|href|action)="(?:https?:)?//', text), f"{path.name} has an absolute or protocol-relative URL"


def test_every_template_asset_goes_through_static_url():
    for path in sorted(TEMPLATES.glob("*.html")):
        for reference in re.findall(r'(?:src|href)="([^"{]*static[^"]*)"', path.read_text()):
            assert False, f"{path.name} hard-codes a static path: {reference}"
