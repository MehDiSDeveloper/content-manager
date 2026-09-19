"""Engine creation, SQLite pragmas and programmatic Alembic migrations."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.text import normalize_for_index

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _on_connect(dbapi_connection: Any, _record: Any) -> None:
    # The search-index triggers call pw_norm(); every connection that writes needs it.
    dbapi_connection.create_function("pw_norm", 1, normalize_for_index, deterministic=True)
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_sqlite_engine(url: str) -> Engine:
    # Pooled connections may be used by worker threads (one at a time), e.g. search warm-up.
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _on_connect)
    return engine


def engine_for_file(path: Path) -> Engine:
    return create_sqlite_engine(f"sqlite:///{path.as_posix()}")


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        config.set_main_option("sqlalchemy.url", url)
    return config


def migrate(engine: Engine) -> None:
    """Upgrade the database behind `engine` to the latest revision."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


class WriteCounter:
    """Increments whenever any session created by the factory flushes changes.

    Lets services cache derived data (tag list, search vocabulary) and know when it is stale.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.value = 0
        event.listen(session_factory, "after_flush", self._bump)

    def _bump(self, *_args: Any) -> None:
        self.value += 1

    def bump(self) -> None:
        """For writes done with raw SQL that never flush."""
        self.value += 1
