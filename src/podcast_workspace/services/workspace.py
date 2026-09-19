"""Composition root: opens the database, migrates it and wires the services.

The UI receives a `Workspace` and talks only to the services on it.
"""

from pathlib import Path

from sqlalchemy import Engine

from podcast_workspace.paths import database_path
from podcast_workspace.repositories.db import (
    WriteCounter,
    engine_for_file,
    make_session_factory,
    migrate,
)
from podcast_workspace.services.content_services import (
    EpisodeNoteService,
    EpisodeService,
    IdeaService,
    TimestampNoteService,
    VoiceService,
)
from podcast_workspace.services.search_service import SearchService
from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.services.tag_service import TagService


class Workspace:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        session_factory = make_session_factory(engine)
        self.writes = WriteCounter(session_factory)
        self.settings = SettingsService(session_factory)
        self.episodes = EpisodeService(session_factory)
        self.episode_notes = EpisodeNoteService(session_factory)
        self.ideas = IdeaService(session_factory)
        self.voices = VoiceService(session_factory)
        self.timestamp_notes = TimestampNoteService(session_factory)
        self.tags = TagService(session_factory)
        self.search = SearchService(session_factory, self.writes)

    @classmethod
    def open(cls, db_path: Path | None = None) -> "Workspace":
        engine = engine_for_file(db_path or database_path())
        migrate(engine)
        return cls(engine)

    def close(self) -> None:
        self._engine.dispose()
