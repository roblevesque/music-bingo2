"""Database models.

Phase 1: hosts and their song library. Phase 2: games, ticket pools, tickets and rounds.
Phase 3: teams (players) and claims.
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


class Branding(SQLModel, table=True):
    """A host's ticket branding, applied to the printed PDF and to the on-screen tickets."""

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", unique=True, index=True)
    header_text: str = Field(default="", max_length=80)  # shown instead of the game name
    footer_text: str = Field(default="", max_length=120)
    accent_color: str = ""  # "#rrggbb", or "" for none
    logo_filename: str = ""  # a PNG inside data/branding/, or "" for none
    updated_at: datetime = Field(default_factory=utcnow)


class Game(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    code: str = Field(index=True, unique=True, max_length=8)  # what players type to join
    status: str = "draft"  # draft -> active -> finished (the play loop is phase 3)
    grid_size: int = 5  # tickets are grid_size x grid_size
    # Phase 3 play state, created now so the table won't need altering later.
    play_order: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    current_index: int = 0  # how many songs have been played: the played songs are play_order[:current_index]
    current_round: int = 1  # Round.number the host is currently running
    # "Run again" copies a game into a new Game in the same series. series_id is the first
    # run's id (None if never re-run); it is deliberately not a foreign key so that deleting
    # one run can't break the others.
    series_id: int | None = None
    run_number: int = 1
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


class Team(SQLModel, table=True):
    """A joined player. Teams have no account: a signed cookie remembers which team a browser is."""

    __table_args__ = (UniqueConstraint("game_id", "name_key"), UniqueConstraint("ticket_id"))

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id", index=True)
    ticket_id: int = Field(foreign_key="ticket.id")
    name: str = Field(max_length=30)
    name_key: str = Field(max_length=30)  # case-folded name, for uniqueness within a game
    marks: list[int] = Field(default_factory=list, sa_column=Column(JSON))  # squares the team has tapped
    created_at: datetime = Field(default_factory=utcnow)


class Claim(SQLModel, table=True):
    """A team calling bingo. Only decided claims are stored ("win" or "rejected")."""

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    round_number: int  # a snapshot, so later edits to rounds don't rewrite history
    round_name: str = ""
    status: str  # "win" or "rejected"
    songs_played: int  # songs played when the claim arrived; equal values are ties
    detail: str = ""  # for the host: which lines were complete, or how far short it was
    created_at: datetime = Field(default_factory=utcnow)
