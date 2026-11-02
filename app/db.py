"""SQLite engine and session handling."""

from fastapi import Request
from sqlalchemy import event
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


def init_db(engine) -> None:
    # create_all is enough while the schema is young. Add Alembic before the
    # first release that real users upgrade across.
    SQLModel.metadata.create_all(engine)


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
