"""Composition root: opens the database, migrates it and wires the services.

The UI receives a `Workspace` and talks only to the services on it.
"""

from pathlib import Path

from sqlalchemy import Engine

from podcast_workspace.paths import database_path
from podcast_workspace.repositories.db import engine_for_file, make_session_factory, migrate
from podcast_workspace.services.settings_service import SettingsService


class Workspace:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        session_factory = make_session_factory(engine)
        self.settings = SettingsService(session_factory)

    @classmethod
    def open(cls, db_path: Path | None = None) -> "Workspace":
        engine = engine_for_file(db_path or database_path())
        migrate(engine)
        return cls(engine)

    def close(self) -> None:
        self._engine.dispose()
