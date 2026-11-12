"""Phone remote: pairing codes, command checking and the slimmed-down state a phone needs.

Pure Python, no framework or database. The remote works by relaying commands through the server to the
host's console (which plays the audio), so everything here is about deciding what may be relayed.
"""

import secrets
import time
from collections import deque
from collections.abc import Callable, Collection

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, which are easy to mix up when typing
CODE_LENGTH = 6
COMMANDS = ("next", "replay", "pause", "skip", "start", "next_round", "effect", "stop_effect")
MAX_COUNT = 100_000


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


class AttemptLimiter:
    """Stops someone guessing pairing codes: after `max_attempts` wrong tries within the window, that
    key (a client address) is blocked until the old attempts age out. In memory, which suits one worker."""

    def __init__(self, max_attempts: int = 8, window_seconds: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.max_attempts, self.window, self._clock = max_attempts, window_seconds, clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        attempts = self._failures.get(key)
        if attempts is None:
            return deque()
        cutoff = self._clock() - self.window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            del self._failures[key]
            return deque()
        return attempts

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._recent(key)  # tidy up first
        self._failures.setdefault(key, deque()).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def _count(text: str, what: str) -> int:
    if not text.isdigit() or int(text) > MAX_COUNT:
        raise ValueError(f"{what} is not a valid number.")
    return int(text)


def validate_command(
    action: str, effect: str = "", expect: str = "", expect_next: str = "", effect_ids: Collection[str] = ()
) -> dict:
    """Check a command from a phone and return the clean version to relay to the console."""
    if action not in COMMANDS:
        raise ValueError("Unknown command.")
    command: dict = {"action": action}
    if action == "effect":
        if effect not in effect_ids:
            raise ValueError("Unknown sound effect.")
        command["effect"] = effect
    if action == "next" and expect != "":
        command["expect"] = _count(expect, "The song count")  # only advance if the game is still at this count
    if action == "skip" and expect_next != "":
        command["expect_next"] = _count(expect_next, "The song")  # only skip if this is still the next song
    return command


def remote_view(host: dict, console_online: bool) -> dict:
    """What a phone needs from the host snapshot: no playlist, no teams, no join or remote codes."""
    current, upcoming, round_ = host.get("current_song"), host.get("next_song"), host.get("round")
    wins = [c for c in host.get("claims", []) if c["status"] == "win"]
    return {
        "name": host["game"]["name"],
        "status": host["game"]["status"],
        "round": {"number": round_["number"], "name": round_["name"], "text": round_["text"]} if round_ else None,
        "has_next_round": bool(round_) and any(r["number"] == round_["number"] + 1 for r in host.get("rounds", [])),
        "songs_played": host["songs_played"],
        "total_songs": host["total_songs"],
        "current": {"title": current["title"], "artist": current["artist"]} if current else None,
        "next": {"id": upcoming["id"], "title": upcoming["title"], "artist": upcoming["artist"]} if upcoming else None,
        "wins": [  # oldest first, so ties read in order
            {"team": c["team"], "ticket": c["ticket"], "songs_played": c["songs_played"], "detail": c["detail"]}
            for c in reversed(wins)
        ],
        "effects": [{"id": e["id"], "label": e["label"], "loop": e["loop"]} for e in host.get("effects", [])],
        "console_online": console_online,
    }
