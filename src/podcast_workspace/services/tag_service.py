"""Tag use cases: CRUD, hierarchy, merge, and forgiving suggestions."""

from collections.abc import Iterable

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.errors import DuplicateTagError, NearDuplicateTagError
from podcast_workspace.domain.tag_matching import TagMatch, find_exact, near_duplicates, rank_tags
from podcast_workspace.repositories.unit_of_work import UnitOfWork

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


class TagService:
    """Keeps an in-memory copy of all tags so suggestions never wait on the database."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._cache: list[Tag] | None = None

    def _tags(self) -> list[Tag]:
        if self._cache is None:
            with UnitOfWork(self._session_factory) as uow:
                self._cache = uow.tags.list_all()
        return self._cache

    def _invalidate(self) -> None:
        self._cache = None

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
        parent_id: int | None = None,
        allow_similar: bool = False,
    ) -> Tag:
        """Create a tag. Exact duplicates are always refused; near-duplicates need consent."""
        tag = Tag(name=name, color=color or self._next_color(), parent_id=parent_id)
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
        return tag

    def rename(self, tag_id: int, name: str) -> Tag:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            tag.rename(name)
            existing = self.find_exact(tag.name)
            if existing is not None and existing.id is not None and existing.id != tag_id:
                raise DuplicateTagError(existing.name, existing.id)
            uow.tags.update(tag)
        self._invalidate()
        return tag

    def recolor(self, tag_id: int, color: str) -> Tag:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            tag.recolor(color)
            uow.tags.update(tag)
        self._invalidate()
        return tag

    def set_parent(self, tag_id: int, parent_id: int | None) -> Tag:
        with UnitOfWork(self._session_factory) as uow:
            tag = uow.tags.get(tag_id)
            tag.parent_id = parent_id
            uow.tags.update(tag)  # repository runs the domain cycle check
        self._invalidate()
        return tag

    def delete(self, tag_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.delete_keeping_children(tag_id)
        self._invalidate()

    def merge(self, source_id: int, target_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.tags.merge_into(source_id, target_id)
        self._invalidate()

    def _next_color(self) -> str:
        return TAG_PALETTE[len(self._tags()) % len(TAG_PALETTE)]
