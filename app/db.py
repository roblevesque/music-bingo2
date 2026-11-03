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
    "game": [("current_round", "INTEGER NOT NULL DEFAULT 1")],
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


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    apply_additive_migrations(engine)


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
