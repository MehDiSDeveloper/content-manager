"""The trash: voices and ideas on their way out (`domain/lifecycle.py`).

`IdeaService.delete` / `VoiceService.delete` put an item here; this service is how it
comes back or goes for good. Purging is the one real delete in the app (the Ideas page's
«delete forever» is the same delete, skipping the trash): the rows go,
and the database cascades their tag links, timestamp notes, transcript and episode
links after them (the tags themselves stay — other items may carry them). A voice's
copy in the workspace's store goes with it; a file anywhere else is never touched.

Neither restoring nor purging is recorded for undo: restoring is undone by deleting
again, and a purge is exactly the thing that cannot be taken back — the UI asks first.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import Voice
from podcast_workspace.domain.lifecycle import TrashKind, purge_at, purge_cutoff
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.voice_store import discard

log = logging.getLogger(__name__)

TrashKey = tuple[TrashKind, int]


@dataclass(frozen=True)
class TrashItem:
    kind: TrashKind
    item_id: int
    title: str  # a voice's file name, an idea's first line
    text: str  # everything the trash page's filter may match: the idea's whole text
    tag_ids: frozenset[int]
    deleted_at: datetime
    purge_at: datetime
    file_path: str = ""  # voices only
    duration_ms: int = 0
    archived: bool = False  # where a restore puts it back

    @property
    def key(self) -> TrashKey:
        return (self.kind, self.item_id)


@dataclass
class PurgeReport:
    voices: set[int] = field(default_factory=set)
    ideas: set[int] = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.voices) + len(self.ideas)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


class TrashService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list(self) -> list[TrashItem]:
        """Most recently trashed first."""
        items: list[TrashItem] = []
        with UnitOfWork(self._sf) as uow:
            for voice in uow.voices.list_trashed():
                assert voice.id is not None and voice.deleted_at is not None
                name = Path(voice.file_path).name
                items.append(
                    TrashItem(
                        TrashKind.VOICE,
                        voice.id,
                        name,
                        name,
                        frozenset(voice.tag_ids),
                        voice.deleted_at,
                        purge_at(voice.deleted_at),
                        voice.file_path,
                        voice.duration_ms,
                        voice.archived,
                    )
                )
            for idea in uow.idea_notes.list_trashed():
                assert idea.id is not None and idea.deleted_at is not None
                items.append(
                    TrashItem(
                        TrashKind.IDEA,
                        idea.id,
                        _first_line(idea.text),
                        idea.text,
                        frozenset(idea.tag_ids),
                        idea.deleted_at,
                        purge_at(idea.deleted_at),
                        archived=idea.archived,
                    )
                )
        items.sort(key=lambda i: i.deleted_at, reverse=True)
        return items

    def count(self) -> int:
        with UnitOfWork(self._sf) as uow:
            return len(uow.voices.list_trashed()) + len(uow.idea_notes.list_trashed())

    def restore(self, keys: Iterable[TrashKey]) -> int:
        """Back where they were — archived items back into the archive. Returns how many."""
        restored = 0
        with UnitOfWork(self._sf) as uow:
            for kind, item_id in keys:
                repo = uow.voices if kind is TrashKind.VOICE else uow.idea_notes
                item = repo.find(item_id)
                if item is None or not item.in_trash:
                    continue
                item.deleted_at = None
                repo.update(item)  # type: ignore[arg-type]
                restored += 1
        return restored

    def purge(self, keys: Iterable[TrashKey]) -> PurgeReport:
        """Delete for good. Only items that are in the trash: a stale selection must never
        reach one that was restored in the meantime."""
        return self._delete(keys, trashed_only=True)

    def delete_forever(self, keys: Iterable[TrashKey]) -> PurgeReport:
        """Delete for good straight from the Ideas page, without the trash in between —
        the same cascade as a purge. The UI asks first."""
        return self._delete(keys, trashed_only=False)

    def _delete(self, keys: Iterable[TrashKey], trashed_only: bool) -> PurgeReport:
        report = PurgeReport()
        files: list[str] = []
        with UnitOfWork(self._sf) as uow:
            for kind, item_id in keys:
                repo = uow.voices if kind is TrashKind.VOICE else uow.idea_notes
                item = repo.find(item_id)
                if item is None or (trashed_only and not item.in_trash):
                    continue
                repo.delete(item_id)
                (report.voices if kind is TrashKind.VOICE else report.ideas).add(item_id)
                if isinstance(item, Voice):
                    files.append(item.file_path)
        for path in files:  # only once the rows are gone for good
            try:
                discard(path)
            except OSError:
                log.warning("stored copy %s not deleted", path, exc_info=True)
        return report

    def purge_expired(self, now: datetime | None = None) -> PurgeReport:
        """Everything that has been in the trash for the full period. Run at startup and
        every so often while the app stays open."""
        cutoff = purge_cutoff(now or datetime.now(UTC))
        with UnitOfWork(self._sf) as uow:
            due = [(TrashKind.VOICE, i) for i in uow.voices.ids_trashed_before(cutoff)]
            due += [(TrashKind.IDEA, i) for i in uow.idea_notes.ids_trashed_before(cutoff)]
        return self.purge(due) if due else PurgeReport()
