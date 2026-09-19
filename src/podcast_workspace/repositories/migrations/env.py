"""Alembic environment. Used both by the CLI (alembic.ini) and by db.migrate() at app start."""

from alembic import context
from sqlalchemy import Connection

from podcast_workspace.paths import database_path
from podcast_workspace.repositories.db import create_sqlite_engine
from podcast_workspace.repositories.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things; batch mode rebuilds tables
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url") or f"sqlite:///{database_path().as_posix()}"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = config.get_main_option("sqlalchemy.url") or f"sqlite:///{database_path().as_posix()}"
    engine = create_sqlite_engine(url)
    with engine.begin() as conn:
        _run(conn)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
