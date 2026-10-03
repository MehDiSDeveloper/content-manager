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
from podcast_workspace.services.backup import BackupService
from podcast_workspace.services.bale_bot import BaleBotService
from podcast_workspace.services.content_services import (
    EpisodeNoteService,
    EpisodeService,
    IdeaService,
    SeasonService,
    TimestampNoteService,
    VoiceService,
)
from podcast_workspace.services.history import HistoryService
from podcast_workspace.services.script_prompt import ScriptPromptService
from podcast_workspace.services.search_service import SearchService
from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.services.source_folder import SourceFolderService
from podcast_workspace.services.tag_service import TagService
from podcast_workspace.services.transcription import TranscriptionService
from podcast_workspace.services.trash import TrashService
from podcast_workspace.services.voice_render import VoiceRenderService


class Workspace:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        session_factory = make_session_factory(engine)
        self.writes = WriteCounter(session_factory)
        # Every use case that can be taken back records its inverse here.
        self.history = HistoryService()
        self.settings = SettingsService(session_factory)
        self.episodes = EpisodeService(session_factory, self.history)
        self.seasons = SeasonService(session_factory, self.history)
        self.episode_notes = EpisodeNoteService(session_factory, self.history)
        self.script_prompt = ScriptPromptService(session_factory)
        self.ideas = IdeaService(session_factory, self.history)
        self.voices = VoiceService(session_factory, self.history)
        self.voice_render = VoiceRenderService(session_factory)
        self.timestamp_notes = TimestampNoteService(session_factory, self.history)
        self.trash = TrashService(session_factory)
        self.source = SourceFolderService(self.settings, self.voices)
        self.tags = TagService(session_factory, self.history)
        self.search = SearchService(session_factory, self.writes)
        self.transcripts = TranscriptionService(session_factory, self.settings)
        self.backup = BackupService(session_factory, self.tags, self.writes, self.settings)
        self.bot = BaleBotService(
            self.settings,
            self.ideas,
            self.voices,
            self.tags,
            self.timestamp_notes,
            self.transcripts,
            self.history,
        )

    @classmethod
    def open(cls, db_path: Path | None = None) -> "Workspace":
        engine = engine_for_file(db_path or database_path())
        migrate(engine)
        return cls(engine)

    def close(self) -> None:
        self.bot.stop()
        self._engine.dispose()
