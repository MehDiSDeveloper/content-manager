"""Domain entities. Plain dataclasses; persistence is the repositories' job.

`id` is None until the entity has been persisted.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from podcast_workspace.domain.rules import (
    MAX_TAGS_PER_ITEM,
    ensure_non_empty,
    ensure_non_negative,
    ensure_tag_limit,
    normalize_color,
    normalize_persian,
    normalize_tag_name,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class EpisodeStatus(StrEnum):
    IDEA = "idea"
    OUTLINING = "outlining"
    RECORDING = "recording"
    EDITING = "editing"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Taggable:
    """Mixin for entities that carry a tag set. `TAG_LIMIT` None means unlimited."""

    TAG_LIMIT: ClassVar[int | None] = None
    tag_ids: set[int]

    def _check_tags(self) -> None:
        if self.TAG_LIMIT is not None:
            ensure_tag_limit(self.tag_ids, self.TAG_LIMIT)

    def set_tags(self, tag_ids: set[int]) -> None:
        if self.TAG_LIMIT is not None:
            ensure_tag_limit(tag_ids, self.TAG_LIMIT)
        self.tag_ids = set(tag_ids)

    def add_tag(self, tag_id: int) -> None:
        self.set_tags(self.tag_ids | {tag_id})

    def remove_tag(self, tag_id: int) -> None:
        self.tag_ids.discard(tag_id)


@dataclass(eq=False)
class Tag:
    name: str
    color: str = "#6b7280"
    parent_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.name = normalize_tag_name(self.name)
        self.color = normalize_color(self.color)

    def rename(self, name: str) -> None:
        self.name = normalize_tag_name(name)

    def recolor(self, color: str) -> None:
        self.color = normalize_color(color)


@dataclass(eq=False)
class Episode(Taggable):
    title: str
    status: EpisodeStatus = EpisodeStatus.IDEA
    next_action: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    last_opened_at: datetime | None = None
    tag_ids: set[int] = field(default_factory=set)
    voice_ids: set[int] = field(default_factory=set)
    idea_note_ids: set[int] = field(default_factory=set)
    id: int | None = None

    def __post_init__(self) -> None:
        self.title = normalize_persian(ensure_non_empty(self.title, "Episode title"))
        self.next_action = normalize_persian(" ".join(self.next_action.split()))

    def touch(self) -> None:
        self.updated_at = utcnow()

    def mark_opened(self) -> None:
        self.last_opened_at = utcnow()


@dataclass(eq=False)
class Voice(Taggable):
    TAG_LIMIT: ClassVar[int | None] = MAX_TAGS_PER_ITEM

    file_path: str
    duration_ms: int = 0
    format: str = ""
    imported_at: datetime = field(default_factory=utcnow)
    tag_ids: set[int] = field(default_factory=set)
    id: int | None = None

    def __post_init__(self) -> None:
        self._check_tags()
        self.file_path = ensure_non_empty(self.file_path, "Voice file path")
        self.duration_ms = ensure_non_negative(self.duration_ms, "duration_ms")
        self.format = self.format.lower().lstrip(".")


@dataclass(eq=False)
class IdeaNote(Taggable):
    TAG_LIMIT: ClassVar[int | None] = MAX_TAGS_PER_ITEM

    text: str
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    tag_ids: set[int] = field(default_factory=set)
    id: int | None = None

    def __post_init__(self) -> None:
        self._check_tags()
        self.text = normalize_persian(ensure_non_empty(self.text, "Idea text"))

    def edit(self, text: str) -> None:
        self.text = normalize_persian(ensure_non_empty(text, "Idea text"))
        self.updated_at = utcnow()


@dataclass(eq=False)
class TimestampNote:
    voice_id: int
    position_ms: int
    text: str
    created_at: datetime = field(default_factory=utcnow)
    id: int | None = None

    def __post_init__(self) -> None:
        self.position_ms = ensure_non_negative(self.position_ms, "position_ms")
        self.text = normalize_persian(ensure_non_empty(self.text, "Timestamp note text"))

    def edit(self, text: str) -> None:
        self.text = normalize_persian(ensure_non_empty(text, "Timestamp note text"))

    def move_to(self, position_ms: int) -> None:
        self.position_ms = ensure_non_negative(position_ms, "position_ms")


@dataclass(eq=False)
class EpisodeNote:
    episode_id: int
    body: str = ""
    title: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    id: int | None = None

    def __post_init__(self) -> None:
        self.title = normalize_persian(self.title.strip())
        self.body = normalize_persian(self.body)

    def edit(self, title: str, body: str) -> None:
        self.title = normalize_persian(title.strip())
        self.body = normalize_persian(body)
        self.updated_at = utcnow()
