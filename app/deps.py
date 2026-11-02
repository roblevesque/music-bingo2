"""Shared FastAPI dependencies."""

from fastapi import Depends, Request
from sqlmodel import Session

from app.db import get_session
from app.models import User


class LoginRequired(Exception):
    """Raised when a page needs a logged-in host; turned into a redirect in main.py."""


def require_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id else None
    if user is None:
        request.session.pop("user_id", None)
        raise LoginRequired()
    return user
