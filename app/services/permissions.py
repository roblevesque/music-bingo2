"""Rules for user accounts. Pure Python, no framework or database."""

import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass

USERNAME_RE = re.compile(r"[a-z0-9_.-]{3,32}\Z")  # \Z, not $, so "name\n" is refused
MIN_PASSWORD_LENGTH = 10
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes (l, 1, O, 0)


def generate_password(length: int = 14) -> str:
    """A random temporary password containing a lower-case letter, a capital and a digit."""
    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password):
            return password


@dataclass(frozen=True)
class Account:
    id: int
    is_admin: bool
    is_active: bool


def leaves_an_admin(accounts: Iterable[Account], target_id: int, *, is_admin: bool, is_active: bool) -> bool:
    """After giving `target_id` these settings, is there still at least one active admin?

    Used to stop the last administrator from demoting or disabling themselves and locking everyone out.
    """
    return any(
        (is_admin and is_active) if account.id == target_id else (account.is_admin and account.is_active)
        for account in accounts
    )
