"""Unit of work: one session + all repositories, committed on clean exit."""

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.repositories.repos import (
    EpisodeNoteRepository,
    EpisodeRepository,
    IdeaNoteRepository,
    SettingsRepository,
    TagRepository,
    TimestampNoteRepository,
    VoiceRepository,
)


class UnitOfWork:
    session: Session
    episodes: EpisodeRepository
    voices: VoiceRepository
    idea_notes: IdeaNoteRepository
    timestamp_notes: TimestampNoteRepository
    episode_notes: EpisodeNoteRepository
    tags: TagRepository
    settings: SettingsRepository

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self.session = self._session_factory()
        self.episodes = EpisodeRepository(self.session)
        self.voices = VoiceRepository(self.session)
        self.idea_notes = IdeaNoteRepository(self.session)
        self.timestamp_notes = TimestampNoteRepository(self.session)
        self.episode_notes = EpisodeNoteRepository(self.session)
        self.tags = TagRepository(self.session)
        self.settings = SettingsRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
