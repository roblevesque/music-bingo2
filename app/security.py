"""Password hashing, CSRF tokens and redirect safety."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

_hasher = PasswordHasher()
# Verified against when a username doesn't exist, so response time doesn't
# reveal which usernames are real.
DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(submitted.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def safe_next(target: str | None, default: str = "/library") -> str:
    """Only allow same-site relative paths, to prevent open redirects."""
    if (
        target
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and target.isprintable()
    ):
        return target
    return default
