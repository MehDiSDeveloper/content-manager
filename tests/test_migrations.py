"""Startup skips Alembic for a database that is already up to date, so the revision it
compares against must be the real head."""

from alembic.script import ScriptDirectory

from podcast_workspace.repositories.db import (
    HEAD_REVISION,
    alembic_config,
    create_sqlite_engine,
    current_revision,
    migrate,
)


def test_head_revision_is_the_newest_migration() -> None:
    assert ScriptDirectory.from_config(alembic_config()).get_current_head() == HEAD_REVISION


def test_migrate_builds_a_new_database_and_then_has_nothing_to_do(tmp_path) -> None:
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    assert current_revision(engine) is None
    migrate(engine)
    assert current_revision(engine) == HEAD_REVISION
    migrate(engine)  # already there: returns before Alembic
    assert current_revision(engine) == HEAD_REVISION
    engine.dispose()
