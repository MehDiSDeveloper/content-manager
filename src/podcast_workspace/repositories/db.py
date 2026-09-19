"""Engine creation, SQLite pragmas and programmatic Alembic migrations."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_sqlite_engine(url: str) -> Engine:
    engine = create_engine(url, future=True)
    event.listen(engine, "connect", _set_sqlite_pragmas)
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
