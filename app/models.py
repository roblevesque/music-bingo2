"""Database models. Phase 1: hosts and their song library.

Games, tickets, players and claims arrive in phases 2 and 3.
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=32)
    password_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class Song(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    filename: str = Field(unique=True)  # server-generated name inside data/clips/
    original_name: str
    title: str = Field(max_length=200)
    artist: str = Field(default="", max_length=200)
    tags: str = ""  # normalised, comma-separated
    duration_ms: int | None = None
    # Non-destructive play window: the file is never re-encoded.
    start_ms: int = 0
    end_ms: int | None = None  # None = play to the end
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def tag_list(self) -> list[str]:
        return [tag for tag in self.tags.split(",") if tag]
