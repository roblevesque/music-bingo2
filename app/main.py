"""Application factory.

Run with:  uv run uvicorn app.main:create_app --factory --reload
"""

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.deps import LoginRequired
from app.routes import auth, branding, games, library, play, run
from app.services.events import Hub
from app.web import BASE_DIR, error_page


ERROR_TITLES = {
    400: "That request didn't work",
    403: "Not allowed",
    404: "Not found",
    405: "Not allowed",
    409: "Not possible right now",
    422: "That didn't look right",
}
PLAIN_DETAILS = {"Not Found", "Forbidden", "Method Not Allowed", "Bad Request"}


def wants_html(request: Request) -> bool:
    """Browsers navigating to a page ask for HTML; our own fetch() calls get JSON errors."""
    return "text/html" in request.headers.get("accept", "")


def friendly_message(status_code: int, detail: object) -> str:
    detail = str(detail or "")
    if status_code == 403 and "CSRF" in detail:
        return "This page was out of date. Reload it and try again."
    if status_code == 403:
        return "You don't have access to that. If you're a player, join the game first."
    if status_code in (404, 405) and detail in PLAIN_DETAILS:
        return "We couldn't find that page."
    return detail or "Something went wrong."


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.db_url)
    init_db(engine)

    app = FastAPI(title="Music Bingo", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.hub = Hub()  # live updates; in-memory, so run a single worker

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key(),
        session_cookie="musicbingo_session",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.https_only,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, _exc: LoginRequired):
        target = "/library"
        if request.method == "GET":
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if not wants_html(request):
            return await http_exception_handler(request, exc)
        title = ERROR_TITLES.get(exc.status_code, "Something went wrong")
        return error_page(request, exc.status_code, title, friendly_message(exc.status_code, exc.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if not wants_html(request):
            return await request_validation_exception_handler(request, exc)
        return error_page(request, 422, ERROR_TITLES[422], "Something was missing or invalid. Go back and try again.")

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        if not wants_html(request):
            return PlainTextResponse("Internal Server Error", status_code=500)
        try:
            return error_page(request, 500, "Something went wrong", "That was our fault. Please try again in a moment.")
        except Exception:  # even the error page failed: send the simplest possible answer
            return HTMLResponse("<h1>Something went wrong</h1>", status_code=500)

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(auth.router)
    app.include_router(library.router)
    app.include_router(games.router)
    app.include_router(branding.router)
    app.include_router(run.router)
    app.include_router(play.router)
    return app
