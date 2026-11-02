"""Database models.

Phase 1: hosts and their song library. Phase 2: games, ticket pools, tickets and rounds.
Players (teams) and claims arrive in phase 3.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.services.patterns import RoundRules


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


class Game(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    code: str = Field(index=True, unique=True, max_length=8)  # what players type to join
    status: str = "draft"  # draft -> active -> finished (the play loop is phase 3)
    grid_size: int = 5  # tickets are grid_size x grid_size
    # Phase 3 play state, created now so the table won't need altering later.
    play_order: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    current_index: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class GameSong(SQLModel, table=True):
    """The song pool for a game."""

    game_id: int = Field(foreign_key="game.id", primary_key=True)
    song_id: int = Field(foreign_key="song.id", primary_key=True, index=True)


class Ticket(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("game_id", "number"),)

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id", index=True)
    number: int  # 1..N within the game
    cells: list[int] = Field(default_factory=list, sa_column=Column(JSON))  # song ids, row-major


class Round(SQLModel, table=True):
    """One round of a game. The host chooses what counts as a win, per round,
    and can change it as the game progresses."""

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id", index=True)
    number: int
    name: str = Field(default="", max_length=60)
    mode: str = "lines"  # "lines" or "full_house"
    lines_required: int = 1
    rows: bool = True
    columns: bool = False
    diagonals: bool = False

    def rules(self) -> RoundRules:
        return RoundRules(
            mode=self.mode,
            lines_required=self.lines_required,
            rows=self.rows,
            columns=self.columns,
            diagonals=self.diagonals,
        )
