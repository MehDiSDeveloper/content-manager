"""Generic repository: maps between one ORM row type and one domain entity type."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from podcast_workspace.domain.errors import NotFoundError
from podcast_workspace.repositories.models import Base, TagRow


class HasId(Protocol):
    id: int | None


class SqlRepository[E: HasId, R: Base](ABC):
    row_type: type[R]
    entity_name: str

    def __init__(self, session: Session) -> None:
        self.session = session

    @abstractmethod
    def _to_domain(self, row: R) -> E: ...

    @abstractmethod
    def _apply(self, entity: E, row: R) -> None:
        """Copy entity state onto the row (the entity has already validated itself)."""

    def _row(self, entity_id: int) -> R:
        row = self.session.get(self.row_type, entity_id)
        if row is None:
            raise NotFoundError(self.entity_name, entity_id)
        return row

    def get(self, entity_id: int) -> E:
        return self._to_domain(self._row(entity_id))

    def find(self, entity_id: int) -> E | None:
        row = self.session.get(self.row_type, entity_id)
        return None if row is None else self._to_domain(row)

    def list_all(self) -> list[E]:
        rows = self.session.scalars(select(self.row_type).order_by(self.row_type.id))
        return [self._to_domain(row) for row in rows]

    def add(self, entity: E) -> E:
        row = self.row_type()
        if entity.id is not None:  # restoring an export keeps the original ids
            row.id = entity.id  # type: ignore[attr-defined]
        self._apply(entity, row)
        self.session.add(row)
        self.session.flush()
        entity.id = row.id  # type: ignore[attr-defined]
        return entity

    def update(self, entity: E) -> E:
        if entity.id is None:
            raise ValueError(f"Cannot update an unsaved {self.entity_name}.")
        self._apply(entity, self._row(entity.id))
        self.session.flush()
        return entity

    def delete(self, entity_id: int) -> None:
        self.session.delete(self._row(entity_id))
        self.session.flush()

    def _tag_rows(self, tag_ids: Collection[int]) -> list[TagRow]:
        wanted = set(tag_ids)
        if not wanted:
            return []
        rows = list(self.session.scalars(select(TagRow).where(TagRow.id.in_(wanted))))
        missing = wanted - {row.id for row in rows}
        if missing:
            raise NotFoundError("Tag", min(missing))
        return rows
