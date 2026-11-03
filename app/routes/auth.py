"""First-run setup, login and logout."""

import re

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import User
from app.security import (
    DUMMY_HASH,
    check_csrf,
    hash_password,
    needs_rehash,
    safe_next,
    verify_password,
)
from app.web import flash, render

router = APIRouter()

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 10


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _has_users(session: Session) -> bool:
    return session.exec(select(User.id).limit(1)).first() is not None


def _start_session(request: Request, user: User) -> None:
    request.session.clear()  # drop any pre-login state, including the old CSRF token
    request.session["user_id"] = user.id


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    if request.session.get("user_id"):
        return _redirect("/library")
    if not _has_users(session):
        return _redirect("/setup")
    return render(request, "home.html")


@router.get("/setup")
def setup_form(request: Request, session: Session = Depends(get_session)):
    if _has_users(session):
        return _redirect("/login")
    return render(request, "setup.html", form={}, errors=[])


@router.post("/setup")
def setup_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    if _has_users(session):  # setup is only open until the first host exists
        return _redirect("/login")
    username = username.strip().lower()
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.")
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != confirm:
        errors.append("Passwords do not match.")
    if errors:
        return render(request, "setup.html", status_code=400, form={"username": username}, errors=errors)
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    _start_session(request, user)
    flash(request, "Host account created. Upload some clips to get started.", "success")
    return _redirect("/library")


@router.get("/login")
def login_form(request: Request, next_url: str = Query("", alias="next")):
    if request.session.get("user_id"):
        return _redirect(safe_next(next_url))
    return render(request, "login.html", form={}, next_url=next_url, error=None)


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("", alias="next"),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    username = username.strip().lower()
    user = session.exec(select(User).where(User.username == username)).first()
    password_ok = verify_password(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not password_ok:
        return render(
            request,
            "login.html",
            status_code=401,
            form={"username": username},
            next_url=next_url,
            error="Incorrect username or password.",
        )
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.add(user)
        session.commit()
    _start_session(request, user)
    return _redirect(safe_next(next_url))


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    request.session.clear()
    return _redirect("/login")
