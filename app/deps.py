"""Shared FastAPI dependencies: who is logged in, and what they may do."""

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.models import User


class LoginRequired(Exception):
    """Raised when a page needs a logged-in host; turned into a redirect in main.py."""


class PasswordChangeRequired(Exception):
    """A generated password must be replaced before anything else; redirects to /account."""


def require_user_any(request: Request, session: Session = Depends(get_session)) -> User:
    """The logged-in user, even if they still have to change their password."""
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id else None
    # A session ends when the account is disabled or its password changes (token_version moves on).
    if user is None or not user.is_active or request.session.get("ver", 0) != user.token_version:
        request.session.pop("user_id", None)
        raise LoginRequired()
    return user


def require_user(user: User = Depends(require_user_any)) -> User:
    if user.must_change_password:
        raise PasswordChangeRequired()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only an administrator can do that.")
    return user


def require_game_creator(user: User = Depends(require_user)) -> User:
    if not user.can_create_games:
        raise HTTPException(status_code=403, detail="Your account isn't allowed to create games. Ask an administrator.")
    return user
