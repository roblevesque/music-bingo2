"""Ticket branding: logo, accent colour, header and footer text."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_user
from app.models import Branding, Game, User, utcnow
from app.security import check_csrf
from app.services.brand_store import branding_row, brand_style, logo_path
from app.services.branding import MAX_UPLOAD_BYTES, InvalidLogo, normalize_hex, process_logo
from app.services.pdf import build_tickets_pdf, fonts_from_settings
from app.web import flash, render

router = APIRouter()

DEFAULT_ACCENT = "#5b4bdb"
MAX_HEADER, MAX_FOOTER = 80, 120


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _form_values(row: Branding | None) -> dict:
    return {
        "header_text": row.header_text if row else "",
        "footer_text": row.footer_text if row else "",
        "use_accent": bool(row and row.accent_color),
        "accent_color": (row.accent_color if row and row.accent_color else DEFAULT_ACCENT),
    }


def _page(request: Request, user: User, session: Session, *, form=None, errors=(), status_code=200):
    row = branding_row(session, user.id)
    has_logo = logo_path(request.app.state.settings, row) is not None
    return render(
        request, "branding.html", status_code=status_code, user=user,
        form=form or _form_values(row), errors=list(errors),
        logo_url=f"/branding/logo?v={row.logo_filename}" if has_logo else None,
    )


@router.get("/branding")
def branding_page(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    return _page(request, user, session)


@router.post("/branding")
async def save_branding(
    request: Request,
    header_text: str = Form(""),
    footer_text: str = Form(""),
    use_accent: bool = Form(False),
    accent_color: str = Form(DEFAULT_ACCENT),
    remove_logo: bool = Form(False),
    logo: UploadFile | None = File(None),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    settings = request.app.state.settings
    header_text, footer_text = " ".join(header_text.split()), " ".join(footer_text.split())
    errors: list[str] = []
    if len(header_text) > MAX_HEADER:
        errors.append(f"The header text can be at most {MAX_HEADER} characters.")
    if len(footer_text) > MAX_FOOTER:
        errors.append(f"The footer text can be at most {MAX_FOOTER} characters.")
    accent = ""
    if use_accent:
        accent = normalize_hex(accent_color) or ""
        if not accent:
            errors.append("The accent colour must look like #5b4bdb.")

    new_logo: bytes | None = None
    if logo is not None and logo.filename:
        data = await logo.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append("The logo must be 1 MB or smaller.")
        else:
            try:
                new_logo = await run_in_threadpool(process_logo, data)
            except InvalidLogo as exc:
                errors.append(f"Logo: {exc}")

    if errors:
        form = {"header_text": header_text, "footer_text": footer_text, "use_accent": use_accent, "accent_color": accent_color}
        return _page(request, user, session, form=form, errors=errors, status_code=400)

    row = branding_row(session, user.id) or Branding(owner_id=user.id)
    old_logo = row.logo_filename
    row.header_text, row.footer_text, row.accent_color, row.updated_at = header_text, footer_text, accent, utcnow()
    if new_logo is not None:
        name = f"logo-{uuid.uuid4().hex}.png"  # a new name each time also busts browser caches
        (settings.branding_dir / name).write_bytes(new_logo)
        row.logo_filename = name
    elif remove_logo:
        row.logo_filename = ""
    session.add(row)
    session.commit()
    if old_logo and old_logo != row.logo_filename:
        (settings.branding_dir / old_logo).unlink(missing_ok=True)
    flash(request, "Branding saved. It applies to printed tickets and to the tickets players see.", "success")
    return _redirect("/branding")


@router.get("/branding/logo")
def own_logo(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    path = logo_path(request.app.state.settings, branding_row(session, user.id))
    if path is None:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    return FileResponse(path, media_type="image/png")


@router.get("/branding/preview.pdf")
def preview_pdf(
    request: Request,
    paper: str = "letter",
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """A sample sheet of tickets with the saved branding, to check how it prints."""
    songs = [(f"Sample song title {i}", f"Sample artist {i}") for i in range(1, 26)]
    sheets = [(1, songs), (2, list(reversed(songs)))]
    try:
        data = build_tickets_pdf(
            "Your game name", 5, sheets, paper=paper, per_page=2,
            fonts=fonts_from_settings(request.app.state.settings),
            brand=brand_style(session, request.app.state.settings, user.id),
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported paper size") from None
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="branding-preview.pdf"', "Cache-Control": "no-store"})


@router.get("/brand/{code}/logo")
def public_logo(request: Request, code: str, session: Session = Depends(get_session)):
    """The host's logo for a game's pages. Public by design: players aren't logged in."""
    clean = "".join(ch for ch in code.upper() if ch.isalnum())
    game = session.exec(select(Game).where(Game.code == clean)).first()
    path = logo_path(request.app.state.settings, branding_row(session, game.owner_id)) if game else None
    if path is None:
        raise HTTPException(status_code=404, detail="No logo")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
