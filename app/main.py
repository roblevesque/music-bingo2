"""Application factory.

Run with:  uv run uvicorn app.main:create_app --factory --reload
"""

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.deps import LoginRequired
from app.routes import auth, games, library, play, run
from app.services.events import Hub
from app.web import BASE_DIR


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

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(auth.router)
    app.include_router(library.router)
    app.include_router(games.router)
    app.include_router(run.router)
    app.include_router(play.router)
    return app
