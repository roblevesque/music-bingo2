"""SQLite engine and session handling."""

from fastapi import Request
from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


# Columns added to existing tables since an earlier phase. create_all only creates
# missing *tables*, so these are added by hand. Add Alembic before real users depend
# on the data; until then this keeps development databases working.
ADDITIVE_COLUMNS = {
    "user": [
        ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("can_create_games", "INTEGER NOT NULL DEFAULT 1"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
        ("token_version", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "song": [("sha256", "TEXT NOT NULL DEFAULT ''")],
    "game": [
        ("current_round", "INTEGER NOT NULL DEFAULT 1"),
        ("series_id", "INTEGER"),
        ("run_number", "INTEGER NOT NULL DEFAULT 1"),
    ],
}


def apply_additive_migrations(engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in ADDITIVE_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns:
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


def ensure_an_admin(engine) -> None:
    """Accounts that predate permissions have no admin: the first account made becomes one."""
    with engine.begin() as connection:
        connection.execute(text(
            'UPDATE "user" SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM "user") '
            'AND NOT EXISTS (SELECT 1 FROM "user" WHERE is_admin = 1)'
        ))


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    apply_additive_migrations(engine)
    ensure_an_admin(engine)


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
