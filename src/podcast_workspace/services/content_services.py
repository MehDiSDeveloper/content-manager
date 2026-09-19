"""Episode, IdeaNote and Voice use cases."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import (
    Episode,
    EpisodeStatus,
    IdeaNote,
    TimestampNote,
    Voice,
)
from podcast_workspace.domain.errors import DomainError
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS, probe


class EpisodeService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_all(self) -> list[Episode]:
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.list_all()

    def get(self, episode_id: int) -> Episode:
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.get(episode_id)

    def open(self, episode_id: int) -> Episode:
        """Fetch and record that the user opened it (drives 'recently opened')."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.mark_opened()
            return uow.episodes.update(episode)

    def create(self, title: str) -> Episode:
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.add(Episode(title=title))

    def update(
        self, episode_id: int, *, title: str, status: EpisodeStatus, next_action: str
    ) -> Episode:
        with UnitOfWork(self._sf) as uow:
            current = uow.episodes.get(episode_id)
            edited = Episode(
                id=current.id,
                title=title,
                status=status,
                next_action=next_action,
                created_at=current.created_at,
                updated_at=current.updated_at,
                last_opened_at=current.last_opened_at,
                tag_ids=current.tag_ids,
                voice_ids=current.voice_ids,
                idea_note_ids=current.idea_note_ids,
            )
            if (edited.title, edited.status, edited.next_action) == (
                current.title,
                current.status,
                current.next_action,
            ):
                return current
            edited.touch()
            return uow.episodes.update(edited)

    def set_tags(self, episode_id: int, tag_ids: Iterable[int]) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.set_tags(set(tag_ids))
            episode.touch()
            return uow.episodes.update(episode)

    def delete(self, episode_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.episodes.delete(episode_id)


class IdeaService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_all(self) -> list[IdeaNote]:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.list_all()

    def get(self, idea_id: int) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.get(idea_id)

    def create(self, text: str, tag_ids: Iterable[int] = ()) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.add(IdeaNote(text=text, tag_ids=set(tag_ids)))

    def update_text(self, idea_id: int, text: str) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            if idea.text == text.strip():
                return idea
            idea.edit(text)
            return uow.idea_notes.update(idea)

    def set_tags(self, idea_id: int, tag_ids: Iterable[int]) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            idea.set_tags(set(tag_ids))
            return uow.idea_notes.update(idea)

    def delete(self, idea_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.idea_notes.delete(idea_id)


@dataclass
class ImportReport:
    imported: list[Voice] = field(default_factory=list)
    already_present: list[Path] = field(default_factory=list)
    unsupported: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


class VoiceService:
    """Voices reference files in place; the workspace never copies, moves or deletes audio."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_all(self) -> list[Voice]:
        with UnitOfWork(self._sf) as uow:
            return uow.voices.list_all()

    def get(self, voice_id: int) -> Voice:
        with UnitOfWork(self._sf) as uow:
            return uow.voices.get(voice_id)

    def import_files(self, paths: Iterable[Path]) -> ImportReport:
        """Blocking (runs ffprobe per file). Call it off the UI thread."""
        report = ImportReport()
        for raw in paths:
            path = raw.resolve()
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                report.unsupported.append(path)
                continue
            try:
                with UnitOfWork(self._sf) as uow:
                    if uow.voices.find_by_path(str(path)) is not None:
                        report.already_present.append(path)
                        continue
                info = probe(path)
                voice = Voice(file_path=str(path), duration_ms=info.duration_ms, format=info.format)
                with UnitOfWork(self._sf) as uow:
                    report.imported.append(uow.voices.add(voice))
            except (OSError, DomainError) as exc:
                report.failed.append((path, str(exc)))
        return report

    def set_tags(self, voice_id: int, tag_ids: Iterable[int]) -> Voice:
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            voice.set_tags(set(tag_ids))
            return uow.voices.update(voice)

    def set_duration(self, voice_id: int, duration_ms: int) -> Voice:
        """Store the exact duration measured by a full decode (import-time probes can be off)."""
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            if abs(voice.duration_ms - duration_ms) < 50:
                return voice
            voice.duration_ms = duration_ms
            return uow.voices.update(voice)

    def delete(self, voice_id: int) -> None:
        """Removes the voice from the workspace only. The audio file stays on disk."""
        with UnitOfWork(self._sf) as uow:
            uow.voices.delete(voice_id)


class TimestampNoteService:
    """Notes pinned to a position inside one Voice. Separate from IdeaNote by design."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_for_voice(self, voice_id: int) -> list[TimestampNote]:
        """Sorted by position_ms (then id)."""
        with UnitOfWork(self._sf) as uow:
            notes = uow.timestamp_notes.list_for_voice(voice_id)
        return sorted(notes, key=lambda n: (n.position_ms, n.id or 0))

    def add(self, voice_id: int, position_ms: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(voice_id)  # NotFoundError if the voice is gone
            return uow.timestamp_notes.add(
                TimestampNote(voice_id=voice_id, position_ms=position_ms, text=text)
            )

    def edit(self, note_id: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            note = uow.timestamp_notes.get(note_id)
            if note.text == text.strip():
                return note
            note.edit(text)
            return uow.timestamp_notes.update(note)

    def delete(self, note_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.timestamp_notes.delete(note_id)
