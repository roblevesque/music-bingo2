"""Template rendering helpers."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.security import get_csrf_token
from app.services.parsing import format_time_ms

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["clock"] = format_time_ms


def static_url(path: str) -> str:
    """Where a static file is served from, as a path on the *current* origin.

    Deliberately not `url_for`, which builds an absolute URL from the request's Host header and scheme.
    Behind a proxy that doesn't forward those, such a URL points the browser at a different origin, and
    browsers apply CORS rules to <script type="module">, so the page breaks with CORS errors.
    """
    return "/static/" + path.lstrip("/")


templates.env.globals["static_url"] = static_url


def error_page(request: Request, status_code: int, title: str, message: str):
    """A friendly error page. Deliberately doesn't touch the session, so it is safe anywhere."""
    settings = request.app.state.settings
    context = {"user": None, "csrf_token": "", "flashes": [], "title": title, "message": message,
               "app_name": settings.app_name, "tagline": settings.tagline}
    return templates.TemplateResponse(request, "error.html", context, status_code=status_code)


def flash(request: Request, message: str, kind: str = "info") -> None:
    """Queue a one-shot message for the next page. Kept short: it lives in the cookie."""
    queue = request.session.setdefault("_flash", [])
    if len(queue) < 5:
        queue.append([kind, message[:200]])


def render(request: Request, name: str, *, status_code: int = 200, **context):
    context["flashes"] = request.session.pop("_flash", [])
    context["csrf_token"] = get_csrf_token(request)
    context.setdefault("user", None)
    settings = request.app.state.settings
    context.setdefault("app_name", settings.app_name)
    context.setdefault("tagline", settings.tagline)
    return templates.TemplateResponse(request, name, context, status_code=status_code)
