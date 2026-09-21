"""Tag use cases: CRUD, merge, and forgiving suggestions. Tags are flat."""

import threading
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.errors import DuplicateTagError, NearDuplicateTagError
from podcast_workspace.domain.tag_matching import TagMatch, find_exact, near_duplicates, rank_tags
from podcast_workspace.repositories.repos import TagUses
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.history import ChangeKind, HistoryService, Target, TargetKind

# Calm, distinguishable colors that read on both light and dark backgrounds.
TAG_PALETTE = (
    "#3b82f6",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#8b5cf6",
    "#ec4899",
    "#14b8a6",
    "#f97316",
    "#6366f1",
    "#84cc16",
)


@dataclass(frozen=True)
class TagResolution:
    requested: str
    tag: Tag
    created: bool  # a new tag was made
    corrected: bool  # an existing tag with a different (near-duplicate) name was used


class TagService:
    """Keeps an in-memory copy of all tags so suggestions never wait on the database.

    Thread-safe: the Bale bot creates tags from its own thread.
    """

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._session_factory = session_factory
        self._history = history
        self._cache: list[Tag] | None = None
        self._lock = threading.RLock()

    def _tags(self) -> list[Tag]:
        with self._lock:
            if self._cache is None:
                with UnitOfWork(self._session_factory) as uow:
                    self._cache = uow.tags.list_all()
            return self._cache

    def _invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def most_used(self, limit: int) -> list[Tag]:
        """Tags by usage count (desc), then name; unused tags fill any remaining places."""
        counts = self.usage_counts()
        ranked = sorted(self._tags(), key=lambda t: (-counts.get(t.id or 0, 0), t.name))
        return ranked[:limit]

    def resolve_or_create(self, name: str) -> TagResolution:
        """Free-text tag entry with no UI to ask the user: an exact match is reused, a
        near-duplicate (the same fuzzy gate as TagInput) is reused instead of creating a
        look-alike, anything else becomes a new tag."""
        with self._lock:
            tags = self._tags()
            exact = find_exact(name, tags)
            if exact is not None:
                return TagResolution(name, exact, created=False, corrected=False)
            similar = near_duplicates(name, tags)
            if similar:
                return TagResolution(name, similar[0].tag, created=False, corrected=True)
            return TagResolution(name, self.create(name), created=True, corrected=False)

    def list_all(self) -> list[Tag]:
        return list(self._tags())

    def by_ids(self, tag_ids: Iterable[int]) -> list[Tag]:
        wanted = set(tag_ids)
        return [t for t in self._tags() if t.id in wanted]

    def get(self, tag_id: int) -> Tag | None:
        return next((t for t in self._tags() if t.id == tag_id), None)

    def usage_counts(self) -> dict[int, int]:
        with UnitOfWork(self._session_factory) as uow:
            return uow.tags.usage_counts()

    def suggest(
        self, query: str, exclude_ids: set[int] | None = None, limit: int = 8
    ) -> list[TagMatch]:
        return rank_tags(query, self._tags(), limit=limit, exclude_ids=exclude_ids)

    def find_exact(self, name: str) -> Tag | None:
        return find_exact(name, self._tags())

    def similar_to(self, name: str, exclude_id: int | None = None) -> list[Tag]:
        return [m.tag for m in near_duplicates(name, self._tags()) if m.tag.id != exclude_id]

    def create(
        self,
        name: str,
        color: str | None = None,
        allow_similar: bool = False,
    ) -> Tag:
        """Create a tag. Exact duplicates are always refused; near-duplicates need consent."""
        with self._lock:
            tag = Tag(name=name, color=color or self._next_color())
            existing = self.find_exact(tag.name)
            if existing is not None and existing.id is not None:
                raise DuplicateTagError(existing.name, existing.id)
            if not allow_similar:
                similar = self.similar_to(tag.name)
                if similar:
                    raise NearDuplicateTagError([t.name for t in similar])
            with UnitOfWork(self._session_factory) as uow:
                uow.tags.add(tag)
            self._invalidate()
        assert tag.id is not None
        snapshot = deepcopy(tag)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.TAG, tag.id),
            undo=lambda: self._drop(snapshot.id),
            redo=lambda: self._put_back(snapshot, TagUses()),
            details=(tag.name,),
            weight=len(tag.name),
        )
        return tag

    def invalidate(self) -> None:
        """Drop the cache after tags changed behind the service's back (data import)."""
        self._invalidate()

    def rename(self, tag_id: int, name: str) -> Tag:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            before = tag.name
            tag.rename(name)
            existing = self.find_exact(tag.name)
            if existing is not None and existing.id is not None and existing.id != tag_id:
                raise DuplicateTagError(existing.name, existing.id)
            uow.tags.update(tag)
        self._invalidate()
        after = tag.name
        self._history.record(
            ChangeKind.RENAME,
            Target(TargetKind.TAG, tag_id),
            undo=lambda: self._set_name(tag_id, before),
            redo=lambda: self._set_name(tag_id, after),
            details=(after, before),
            weight=len(before) + len(after),
        )
        return tag

    def recolor(self, tag_id: int, color: str) -> Tag:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            before = tag.color
            tag.recolor(color)
            uow.tags.update(tag)
        self._invalidate()
        after, name = tag.color, tag.name
        self._history.record(
            ChangeKind.RECOLOR,
            Target(TargetKind.TAG, tag_id),
            undo=lambda: self._set_color(tag_id, before),
            redo=lambda: self._set_color(tag_id, after),
            details=(name,),
            weight=len(name),
        )
        return tag

    def delete(self, tag_id: int) -> None:
        """Undo puts the tag back on everything it was on — that is the whole point of
        being able to delete a tag without first checking what carries it."""
        with UnitOfWork(self._session_factory) as uow:
            tag = deepcopy(uow.tags.get(tag_id))
            uses = uow.tags.uses_of(tag_id)
            uow.tags.delete(tag_id)
        self._invalidate()
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.TAG, tag_id),
            undo=lambda: self._put_back(tag, uses),
            redo=lambda: self._drop(tag_id),
            details=(tag.name,),
            weight=len(tag.name) + len(uses),
        )

    def merge(self, source_id: int, target_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            source = deepcopy(uow.tags.get(source_id))
            target = uow.tags.get(target_id)
            mine = uow.tags.uses_of(source_id)
            theirs = uow.tags.uses_of(target_id)
            uow.tags.merge_into(source_id, target_id)
        self._invalidate()
        # What the target gained by the merge, and must give back when it is undone.
        gained = TagUses(
            mine.episodes - theirs.episodes,
            mine.voices - theirs.voices,
            mine.ideas - theirs.ideas,
        )
        self._history.record(
            ChangeKind.MERGE,
            Target(TargetKind.TAG, target_id),
            undo=lambda: self._split(source, mine, gained, target_id),
            redo=lambda: self._merge(source_id, target_id),
            details=(source.name, target.name),
            weight=len(source.name) + len(mine),
        )

    # inverses -------------------------------------------------------------------------
    def _set_name(self, tag_id: int, name: str) -> None:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            tag.rename(name)
            uow.tags.update(tag)
        self._invalidate()

    def _set_color(self, tag_id: int, color: str) -> None:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            tag.recolor(color)
            uow.tags.update(tag)
        self._invalidate()

    def _put_back(self, tag: Tag, uses: TagUses) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.add(deepcopy(tag))
            if tag.id is not None:
                uow.tags.add_uses(tag.id, uses)
        self._invalidate()

    def _drop(self, tag_id: int | None) -> None:
        if tag_id is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.delete(tag_id)
        self._invalidate()

    def _merge(self, source_id: int, target_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.merge_into(source_id, target_id)
        self._invalidate()

    def _split(
        self,
        source: Tag,
        uses: TagUses,
        gained: TagUses,
        target_id: int,
    ) -> None:
        """Undo a merge: bring the source tag back, give it its uses, and
        take off the target the uses it only has because of the merge."""
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.add(deepcopy(source))
            if source.id is not None:
                uow.tags.add_uses(source.id, uses)
            uow.tags.remove_uses(target_id, gained)
        self._invalidate()

    def _next_color(self) -> str:
        return TAG_PALETTE[len(self._tags()) % len(TAG_PALETTE)]
