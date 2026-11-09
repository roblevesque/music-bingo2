"""User accounts: an administrator adds users and sets what they may do; everyone manages their own password."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_admin, require_user_any
from app.models import User
from app.security import check_csrf, hash_password, verify_password
from app.services.permissions import (
    MIN_PASSWORD_LENGTH, USERNAME_RE, Account, generate_password, leaves_an_admin,
)
from app.web import flash, render

router = APIRouter()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _accounts(session: Session) -> list[Account]:
    return [Account(u.id, u.is_admin, u.is_active) for u in session.exec(select(User)).all()]


def _target(session: Session, user_id: int) -> User:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


def _page(request: Request, admin: User, session: Session, *, credentials=None, errors=(), status_code=200):
    users = session.exec(select(User).order_by(User.id)).all()
    return render(request, "users.html", status_code=status_code, user=admin, users=users,
                  credentials=credentials, errors=list(errors))


# ---------------------------------------------------------------- administrators


@router.get("/users")
def users_page(request: Request, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    return _page(request, admin, session)


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(""),
    can_create_games: bool = Form(False),
    is_admin: bool = Form(False),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Make an account with a generated password. It is shown once, here, and must be changed at first login."""
    check_csrf(request, csrf_token)
    username = username.strip().lower()
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.")
    elif session.exec(select(User.id).where(User.username == username)).first() is not None:
        errors.append("That username is already taken.")
    if errors:
        return _page(request, admin, session, errors=errors, status_code=400)
    password = generate_password()
    session.add(User(
        username=username, password_hash=hash_password(password), is_admin=is_admin,
        can_create_games=can_create_games, must_change_password=True,
    ))
    session.commit()
    return _page(request, admin, session, credentials={"username": username, "password": password, "action": "created"})


@router.post("/users/{user_id}/permissions")
def update_permissions(
    request: Request,
    user_id: int,
    can_create_games: bool = Form(False),
    is_admin: bool = Form(False),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    target = _target(session, user_id)
    if not leaves_an_admin(_accounts(session), target.id, is_admin=is_admin, is_active=target.is_active):
        flash(request, "At least one active administrator is needed, so that can't be changed.", "error")
        return _redirect("/users")
    target.can_create_games, target.is_admin = can_create_games, is_admin
    session.add(target)
    session.commit()
    flash(request, f"Updated {target.username}.", "success")
    return _redirect("/users")


@router.post("/users/{user_id}/reset-password")
def reset_password(
    request: Request,
    user_id: int,
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    target = _target(session, user_id)
    if target.id == admin.id:
        flash(request, "Change your own password from the Account page.", "error")
        return _redirect("/users")
    password = generate_password()
    target.password_hash = hash_password(password)
    target.must_change_password = True
    target.token_version += 1  # signs them out everywhere
    session.add(target)
    session.commit()
    return _page(request, admin, session, credentials={"username": target.username, "password": password, "action": "reset"})


@router.post("/users/{user_id}/active")
def set_active(
    request: Request,
    user_id: int,
    active: str = Form("1"),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    target = _target(session, user_id)
    make_active = active == "1"
    if not make_active and target.id == admin.id:
        flash(request, "You can't disable your own account.", "error")
        return _redirect("/users")
    if not leaves_an_admin(_accounts(session), target.id, is_admin=target.is_admin, is_active=make_active):
        flash(request, "At least one active administrator is needed, so that can't be changed.", "error")
        return _redirect("/users")
    target.is_active = make_active
    if not make_active:
        target.token_version += 1  # signs them out everywhere
    session.add(target)
    session.commit()
    flash(request, f"{'Enabled' if make_active else 'Disabled'} {target.username}.", "success")
    return _redirect("/users")


# ---------------------------------------------------------------- everyone: their own account


def _account_page(request: Request, user: User, *, errors=(), status_code=200):
    return render(request, "account.html", status_code=status_code, user=user, errors=list(errors),
                  forced=user.must_change_password, min_length=MIN_PASSWORD_LENGTH)


@router.get("/account")
def account_page(request: Request, user: User = Depends(require_user_any)):
    return _account_page(request, user)


@router.post("/account")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user_any),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    errors = []
    if not verify_password(user.password_hash, current_password):
        errors.append("Your current password isn't right.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        errors.append(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if new_password != confirm:
        errors.append("The new passwords don't match.")
    if not errors and new_password == current_password:
        errors.append("Choose a password different from the current one.")
    if errors:
        return _account_page(request, user, errors=errors, status_code=400)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.token_version += 1  # every other session ends; this one carries on below
    session.add(user)
    session.commit()
    request.session["ver"] = user.token_version
    flash(request, "Your password has been changed.", "success")
    return _redirect("/library")
