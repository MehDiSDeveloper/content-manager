"""Episode, IdeaNote and Voice use cases.

Undoable use cases record their own inverse (`services/history.py`): the snapshot a
change needs in order to be taken back is captured here, beside the operation that made
it, so the UI never has to know how to reverse anything. Snapshots hold ids and the few
fields that change — never a copy of the database.

What is not recorded, and why: importing voices (additive, and the files stay on disk),
`open()` and `set_duration` (bookkeeping, not edits), and anything the Bale bot does
(it runs inside `history.suspended()`: the user's stack is for the user's own actions).
"""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import (
    Episode,
    EpisodeNote,
    EpisodeStatus,
    IdeaNote,
    TimestampNote,
    Transcript,
    Voice,
    utcnow,
)
from podcast_workspace.domain.errors import DomainError
from podcast_workspace.domain.smart_links import (
    LinkCandidate,
    LinkKind,
    SmartLink,
    rank_smart_links,
)
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS, probe
from podcast_workspace.services.history import ChangeKind, HistoryService, Target, TargetKind


def _short(text: str, width: int = 60) -> str:
    """A name for an undo entry: the first line, shortened."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


def _tag_names(uow: UnitOfWork, tag_ids: Iterable[int]) -> tuple[str, ...]:
    wanted = set(tag_ids)
    return tuple(t.name for t in uow.tags.list_all() if t.id in wanted)


def _known_tags(uow: UnitOfWork, tag_ids: Iterable[int]) -> set[int]:
    """Tags of the snapshot that still exist (one deleted since must not block an undo)."""
    alive = {t.id for t in uow.tags.list_all()}
    return {t for t in tag_ids if t in alive}


def _relink(
    uow: UnitOfWork, episode_ids: frozenset[int], kind: LinkKind, item_id: int | None
) -> None:
    """Put a restored voice / idea back into the episodes that referenced it."""
    if item_id is None:
        return
    for episode_id in episode_ids:
        episode = uow.episodes.find(episode_id)
        if episode is None:
            continue
        ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
        ids.add(item_id)
        uow.episodes.update(episode)


class EpisodeService:
    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

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
            episode = uow.episodes.add(Episode(title=title))
        assert episode.id is not None
        snapshot = deepcopy(episode)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.EPISODE, episode.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, ()),
            details=(episode.title,),
            weight=len(episode.title),
        )
        return episode

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
            before = (current.title, current.status, current.next_action, current.updated_at)
            edited.touch()
            saved = uow.episodes.update(edited)
        after = (saved.title, saved.status, saved.next_action, saved.updated_at)
        # One step per run of typing, not one per field committed.
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_fields(episode_id, before),
            redo=lambda: self._set_fields(episode_id, after),
            details=(saved.title,),
            weight=len(saved.title) + len(saved.next_action),
            merge_key=f"episode-fields:{episode_id}",
        )
        return saved

    def set_tags(self, episode_id: int, tag_ids: Iterable[int]) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            before, after = set(episode.tag_ids), set(tag_ids)
            if before == after:
                return episode
            stamp = episode.updated_at
            episode.set_tags(after)
            episode.touch()
            saved = uow.episodes.update(episode)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        touched = saved.updated_at
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_tags(episode_id, before, stamp),
            redo=lambda: self._set_tags(episode_id, after, touched),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def set_status(self, episode_id: int, status: EpisodeStatus) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            if episode.status is status:
                return episode
            before, stamp = episode.status, episode.updated_at
            episode.status = status
            episode.touch()
            saved = uow.episodes.update(episode)
        touched, title = saved.updated_at, saved.title
        self._history.record(
            ChangeKind.STATUS,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_status(episode_id, before, stamp),
            redo=lambda: self._set_status(episode_id, status, touched),
            details=(status.value, title),
            weight=len(title),
        )
        return saved

    def link(self, episode_id: int, kind: LinkKind, item_id: int, linked: bool) -> Episode:
        """Attach or detach a Voice / IdeaNote. Counts as touching the episode."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
            if (item_id in ids) == linked:
                return episode
            stamp = episode.updated_at
            if linked:
                ids.add(item_id)
            else:
                ids.discard(item_id)
            episode.touch()
            saved = uow.episodes.update(episode)
            name = self._item_name(uow, kind, item_id)
        touched = saved.updated_at
        self._history.record(
            ChangeKind.LINKED if linked else ChangeKind.UNLINKED,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_link(episode_id, kind, item_id, not linked, stamp),
            redo=lambda: self._set_link(episode_id, kind, item_id, linked, touched),
            details=(name,),
            weight=len(name),
        )
        return saved

    @staticmethod
    def _item_name(uow: UnitOfWork, kind: LinkKind, item_id: int) -> str:
        if kind is LinkKind.VOICE:
            voice = uow.voices.find(item_id)
            return "" if voice is None else Path(voice.file_path).name
        idea = uow.idea_notes.find(item_id)
        return "" if idea is None else _short(idea.text)

    def smart_links(self, episode_id: int) -> list[SmartLink]:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            candidates = [
                LinkCandidate(LinkKind.VOICE, v.id, frozenset(v.tag_ids), v.imported_at)
                for v in uow.voices.list_all()
                if v.id is not None
            ] + [
                LinkCandidate(LinkKind.IDEA, i.id, frozenset(i.tag_ids), i.updated_at)
                for i in uow.idea_notes.list_all()
                if i.id is not None
            ]
        return rank_smart_links(episode.tag_ids, candidates)

    def resume(self) -> "ResumeInfo | None":
        """The last opened episode and its most recently edited note."""
        with UnitOfWork(self._sf) as uow:
            opened = [e for e in uow.episodes.list_all() if e.last_opened_at is not None]
            if not opened:
                return None
            episode = max(opened, key=lambda e: e.last_opened_at or e.updated_at)
            assert episode.id is not None
            notes = uow.episode_notes.list_for_episode(episode.id)
        note = max(notes, key=lambda n: n.updated_at) if notes else None
        return ResumeInfo(episode, note)

    def delete(self, episode_id: int) -> None:
        """The episode and its notes go together, so undo brings both back."""
        with UnitOfWork(self._sf) as uow:
            episode = deepcopy(uow.episodes.get(episode_id))
            notes = tuple(deepcopy(n) for n in uow.episode_notes.list_for_episode(episode_id))
            uow.episodes.delete(episode_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._restore(episode, notes),
            redo=lambda: self._erase(episode_id),
            details=(episode.title,),
            weight=len(episode.title) + sum(len(n.title) + len(n.body) for n in notes),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_fields(
        self, episode_id: int, values: tuple[str, EpisodeStatus, str, datetime]
    ) -> None:
        title, status, next_action, updated_at = values
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.title, episode.status, episode.next_action = title, status, next_action
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_tags(self, episode_id: int, tag_ids: set[int], updated_at: datetime) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.set_tags(_known_tags(uow, tag_ids))
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_status(self, episode_id: int, status: EpisodeStatus, updated_at: datetime) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.status = status
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_link(
        self, episode_id: int, kind: LinkKind, item_id: int, linked: bool, updated_at: datetime
    ) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
            item = (
                uow.voices.find(item_id) if kind is LinkKind.VOICE else uow.idea_notes.find(item_id)
            )
            if linked:
                if item is None:
                    return  # the item itself is gone: there is nothing to link back
                ids.add(item_id)
            else:
                ids.discard(item_id)
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _restore(self, episode: Episode, notes: tuple[EpisodeNote, ...]) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = deepcopy(episode)
            restored.tag_ids = _known_tags(uow, restored.tag_ids)
            restored.voice_ids &= {v.id for v in uow.voices.list_all()}
            restored.idea_note_ids &= {i.id for i in uow.idea_notes.list_all()}
            uow.episodes.add(restored)
            for note in notes:
                uow.episode_notes.add(deepcopy(note))

    def _erase(self, episode_id: int | None) -> None:
        if episode_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.episodes.delete(episode_id)


@dataclass(frozen=True)
class ResumeInfo:
    episode: Episode
    note: EpisodeNote | None


class EpisodeNoteService:
    """Long-form notes inside an episode. Every change touches the episode (stale marker)."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_for_episode(self, episode_id: int) -> list[EpisodeNote]:
        with UnitOfWork(self._sf) as uow:
            return uow.episode_notes.list_for_episode(episode_id)

    def get(self, note_id: int) -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            return uow.episode_notes.get(note_id)

    def create(self, episode_id: int, title: str = "", body: str = "") -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            stamp = self._touch(uow, episode_id)
            note = uow.episode_notes.add(EpisodeNote(episode_id=episode_id, title=title, body=body))
        assert note.id is not None
        snapshot = deepcopy(note)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.EPISODE_NOTE, note.id, episode_id),
            undo=lambda: self._erase(snapshot.id, stamp),
            redo=lambda: self._restore(snapshot),
            details=(_short(note.title or note.body),),
            weight=len(note.title) + len(note.body),
        )
        return note

    def update(self, note_id: int, title: str, body: str) -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            if (note.title, note.body) == (title.strip(), body):
                return note
            before = (note.title, note.body, note.updated_at)
            stamp = self._touch(uow, note.episode_id)
            note.edit(title, body)
            saved = uow.episode_notes.update(note)
        after = (saved.title, saved.body, saved.updated_at)
        # The editor's own Ctrl+Z covers keystrokes; this step covers a whole writing run.
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.EPISODE_NOTE, note_id, saved.episode_id),
            undo=lambda: self._set_text(note_id, before, stamp),
            redo=lambda: self._set_text(note_id, after, None),
            details=(_short(saved.title or saved.body),),
            weight=len(saved.title) + len(saved.body),
            merge_key=f"episode-note:{note_id}",
        )
        return saved

    def delete(self, note_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            note = deepcopy(uow.episode_notes.get(note_id))
            stamp = self._touch(uow, note.episode_id)
            uow.episode_notes.delete(note_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.EPISODE_NOTE, note_id, note.episode_id),
            undo=lambda: self._restore(note, stamp),
            redo=lambda: self._erase(note_id, None),
            details=(_short(note.title or note.body),),
            weight=len(note.title) + len(note.body),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(
        self, note_id: int, values: tuple[str, str, datetime], stamp: datetime | None
    ) -> None:
        title, body, updated_at = values
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            note.title, note.body, note.updated_at = title, body, updated_at
            uow.episode_notes.update(note)
            self._touch(uow, note.episode_id, stamp)

    def _restore(self, note: EpisodeNote, stamp: datetime | None = None) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.episodes.get(note.episode_id)  # the episode must still be there
            uow.episode_notes.add(deepcopy(note))
            self._touch(uow, note.episode_id, stamp)

    def _erase(self, note_id: int | None, stamp: datetime | None) -> None:
        if note_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            uow.episode_notes.delete(note_id)
            self._touch(uow, note.episode_id, stamp)

    @staticmethod
    def _touch(uow: UnitOfWork, episode_id: int, when: datetime | None = None) -> datetime:
        """Mark the episode edited (or put its old mark back). Returns the previous value."""
        episode = uow.episodes.find(episode_id)
        if episode is None:
            return utcnow()
        before = episode.updated_at
        if when is None:
            episode.touch()
        else:
            episode.updated_at = when
        uow.episodes.update(episode)
        return before


class IdeaService:
    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_all(self) -> list[IdeaNote]:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.list_all()

    def get(self, idea_id: int) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.get(idea_id)

    def create(self, text: str, tag_ids: Iterable[int] = ()) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.add(IdeaNote(text=text, tag_ids=set(tag_ids)))
        assert idea.id is not None
        snapshot = deepcopy(idea)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.IDEA, idea.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, frozenset()),
            details=(_short(idea.text),),
            weight=len(idea.text),
        )
        return idea

    def update_text(self, idea_id: int, text: str) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            if idea.text == text.strip():
                return idea
            before = (idea.text, idea.updated_at)
            idea.edit(text)
            saved = uow.idea_notes.update(idea)
        after = (saved.text, saved.updated_at)
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: self._set_text(idea_id, before),
            redo=lambda: self._set_text(idea_id, after),
            details=(_short(saved.text),),
            weight=len(saved.text),
            merge_key=f"idea-text:{idea_id}",
        )
        return saved

    def set_tags(self, idea_id: int, tag_ids: Iterable[int]) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            before, after = set(idea.tag_ids), set(tag_ids)
            if before == after:
                return idea
            idea.set_tags(after)
            saved = uow.idea_notes.update(idea)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: self._set_tags(idea_id, before),
            redo=lambda: self._set_tags(idea_id, after),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def delete(self, idea_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            idea = deepcopy(uow.idea_notes.get(idea_id))
            episodes = frozenset(uow.episodes.ids_with_idea(idea_id))
            uow.idea_notes.delete(idea_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: self._restore(idea, episodes),
            redo=lambda: self._erase(idea_id),
            details=(_short(idea.text),),
            weight=len(idea.text),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(self, idea_id: int, values: tuple[str, datetime]) -> None:
        text, updated_at = values
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            idea.text, idea.updated_at = text, updated_at
            uow.idea_notes.update(idea)

    def _set_tags(self, idea_id: int, tag_ids: set[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            idea.set_tags(_known_tags(uow, tag_ids))
            uow.idea_notes.update(idea)

    def _restore(self, idea: IdeaNote, episodes: frozenset[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = deepcopy(idea)
            restored.tag_ids = _known_tags(uow, restored.tag_ids)
            uow.idea_notes.add(restored)
            _relink(uow, episodes, LinkKind.IDEA, idea.id)

    def _erase(self, idea_id: int | None) -> None:
        if idea_id is None:
            return
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

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

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
            before, after = set(voice.tag_ids), set(tag_ids)
            if before == after:
                return voice
            voice.set_tags(after)
            saved = uow.voices.update(voice)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.VOICE, voice_id),
            undo=lambda: self._set_tags(voice_id, before),
            redo=lambda: self._set_tags(voice_id, after),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def set_duration(self, voice_id: int, duration_ms: int) -> Voice:
        """Store the exact duration measured by a full decode (import-time probes can be off)."""
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            if abs(voice.duration_ms - duration_ms) < 50:
                return voice
            voice.duration_ms = duration_ms
            return uow.voices.update(voice)

    def delete(self, voice_id: int) -> None:
        """Removes the voice from the workspace only. The audio file stays on disk.

        Its timestamp notes, transcript and episode links go with it, so undo puts all of
        them back: losing a transcript to a mis-click would cost a long re-run.
        """
        with UnitOfWork(self._sf) as uow:
            voice = deepcopy(uow.voices.get(voice_id))
            notes = tuple(deepcopy(n) for n in uow.timestamp_notes.list_for_voice(voice_id))
            transcript = deepcopy(uow.transcripts.for_voice(voice_id))
            episodes = frozenset(uow.episodes.ids_with_voice(voice_id))
            uow.voices.delete(voice_id)
        name = Path(voice.file_path).name
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.VOICE, voice_id),
            undo=lambda: self._restore(voice, notes, transcript, episodes),
            redo=lambda: self._erase(voice_id),
            details=(name,),
            weight=len(name)
            + sum(len(n.text) for n in notes)
            + (len(transcript.text) if transcript is not None else 0),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_tags(self, voice_id: int, tag_ids: set[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            voice.set_tags(_known_tags(uow, tag_ids))
            uow.voices.update(voice)

    def _restore(
        self,
        voice: Voice,
        notes: tuple[TimestampNote, ...],
        transcript: Transcript | None,
        episodes: frozenset[int],
    ) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = deepcopy(voice)
            restored.tag_ids = _known_tags(uow, restored.tag_ids)
            uow.voices.add(restored)
            for note in notes:
                uow.timestamp_notes.add(deepcopy(note))
            if transcript is not None:
                uow.transcripts.add(deepcopy(transcript))
            _relink(uow, episodes, LinkKind.VOICE, voice.id)

    def _erase(self, voice_id: int | None) -> None:
        if voice_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.voices.delete(voice_id)


class TimestampNoteService:
    """Notes pinned to a position inside one Voice. Separate from IdeaNote by design."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_for_voice(self, voice_id: int) -> list[TimestampNote]:
        """Sorted by position_ms (then id)."""
        with UnitOfWork(self._sf) as uow:
            notes = uow.timestamp_notes.list_for_voice(voice_id)
        return sorted(notes, key=lambda n: (n.position_ms, n.id or 0))

    def counts_by_voice(self) -> dict[int, int]:
        with UnitOfWork(self._sf) as uow:
            return uow.timestamp_notes.counts_by_voice()

    def add(self, voice_id: int, position_ms: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(voice_id)  # NotFoundError if the voice is gone
            note = uow.timestamp_notes.add(
                TimestampNote(voice_id=voice_id, position_ms=position_ms, text=text)
            )
        assert note.id is not None
        snapshot = deepcopy(note)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.TIMESTAMP_NOTE, note.id, voice_id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot),
            details=(_short(note.text),),
            weight=len(note.text),
        )
        return note

    def edit(self, note_id: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            note = uow.timestamp_notes.get(note_id)
            if note.text == text.strip():
                return note
            before, voice_id = note.text, note.voice_id
            note.edit(text)
            saved = uow.timestamp_notes.update(note)
        after = saved.text
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.TIMESTAMP_NOTE, note_id, voice_id),
            undo=lambda: self._set_text(note_id, before),
            redo=lambda: self._set_text(note_id, after),
            details=(_short(after),),
            weight=len(after),
            merge_key=f"stamp:{note_id}",
        )
        return saved

    def delete(self, note_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            note = deepcopy(uow.timestamp_notes.get(note_id))
            uow.timestamp_notes.delete(note_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.TIMESTAMP_NOTE, note_id, note.voice_id),
            undo=lambda: self._restore(note),
            redo=lambda: self._erase(note_id),
            details=(_short(note.text),),
            weight=len(note.text),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(self, note_id: int, text: str) -> None:
        with UnitOfWork(self._sf) as uow:
            note = uow.timestamp_notes.get(note_id)
            note.edit(text)
            uow.timestamp_notes.update(note)

    def _restore(self, note: TimestampNote) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(note.voice_id)  # the voice must still be there
            uow.timestamp_notes.add(deepcopy(note))

    def _erase(self, note_id: int | None) -> None:
        if note_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.timestamp_notes.delete(note_id)
