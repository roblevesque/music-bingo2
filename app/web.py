"""Template rendering helpers."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.security import get_csrf_token
from app.services.parsing import format_time_ms

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["clock"] = format_time_ms


def error_page(request: Request, status_code: int, title: str, message: str):
    """A friendly error page. Deliberately doesn't touch the session, so it is safe anywhere."""
    context = {"user": None, "csrf_token": "", "flashes": [], "title": title, "message": message}
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
    return templates.TemplateResponse(request, name, context, status_code=status_code)
