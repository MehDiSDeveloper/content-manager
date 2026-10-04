"""Domain entities. Plain dataclasses; persistence is the repositories' job.

`id` is None until the entity has been persisted.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from podcast_workspace.domain.publish import PublishChecklist
from podcast_workspace.domain.rules import (
    MAX_TAGS_PER_ITEM,
    ensure_non_empty,
    ensure_non_negative,
    ensure_tag_limit,
    normalize_color,
    normalize_persian,
    normalize_tag_name,
)
from podcast_workspace.domain.script_brief import ScriptBrief


def utcnow() -> datetime:
    return datetime.now(UTC)


class EpisodeStatus(StrEnum):
    """The production pipeline, in order (Kanban columns follow this order)."""

    IDEA = "idea"
    OUTLINE = "outline"
    RECORDED = "recorded"
    SCRIPT_READY = "script_ready"
    EDITED = "edited"
    PUBLISHED = "published"


class Shelved:
    """Mixin for items that can be archived and put in the trash (`domain/lifecycle.py`).

    Both are moments, not flags: when it was archived, when it went in the trash (the
    purge counts from there). None means it is not.
    """

    archived_at: datetime | None
    deleted_at: datetime | None

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    @property
    def in_trash(self) -> bool:
        return self.deleted_at is not None


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
    id: int | None = None

    def __post_init__(self) -> None:
        self.name = normalize_tag_name(self.name)
        self.color = normalize_color(self.color)

    def rename(self, name: str) -> None:
        self.name = normalize_tag_name(name)

    def recolor(self, color: str) -> None:
        self.color = normalize_color(color)


@dataclass(eq=False)
class Season:
    """A run of episodes. Episodes belong to at most one; deleting a season keeps them.

    Its brief is what keeps a run of episodes pointed somewhere. `readme` is the
    producer's own: what the season is for, its strategy, rules and goals, and the path
    it takes; it is what the script prompt hands the AI. `about` is the season as
    listeners are told of it. Both are free text, and either may be empty.
    """

    title: str
    readme: str = ""
    about: str = ""
    # Where it stands among the seasons (None: not numbered yet), see `in_order`.
    number: int | None = None
    created_at: datetime = field(default_factory=utcnow)
    id: int | None = None

    def __post_init__(self) -> None:
        self.title = normalize_persian(ensure_non_empty(self.title, "Season title"))
        self.number = self.number or None
        self.readme = normalize_persian(self.readme)
        self.about = normalize_persian(self.about)

    def rename(self, title: str) -> None:
        self.title = normalize_persian(ensure_non_empty(title, "Season title"))

    def write_brief(self, readme: str, about: str) -> None:
        self.readme = normalize_persian(readme)
        self.about = normalize_persian(about)


def in_order[T: (Season, Episode)](items: Iterable[T]) -> list[T]:
    """Seasons, or a season's episodes, in their order: by number, then the unnumbered
    in the order they were made (an episode is usually made when its turn comes)."""
    return sorted(items, key=lambda x: (x.number is None, x.number or 0, x.created_at, x.id or 0))


@dataclass(eq=False)
class Episode(Taggable):
    title: str
    status: EpisodeStatus = EpisodeStatus.IDEA
    next_action: str = ""
    season_id: int | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    last_opened_at: datetime | None = None
    tag_ids: set[int] = field(default_factory=set)
    voice_ids: set[int] = field(default_factory=set)
    idea_note_ids: set[int] = field(default_factory=set)
    publish: PublishChecklist = field(default_factory=PublishChecklist)
    brief: ScriptBrief = field(default_factory=ScriptBrief)
    # What the episode ended up saying, in a few lines: the script prompts of the
    # season's later episodes carry it, so each one knows the story so far.
    summary: str = ""
    # Its place in its season, given by hand: one made early can say it comes third.
    number: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.title = normalize_persian(ensure_non_empty(self.title, "Episode title"))
        self.number = self.number or None
        self.next_action = normalize_persian(" ".join(self.next_action.split()))
        self.summary = normalize_persian(self.summary)

    def touch(self) -> None:
        self.updated_at = utcnow()

    def mark_opened(self) -> None:
        self.last_opened_at = utcnow()

    def write_summary(self, summary: str) -> None:
        self.summary = normalize_persian(summary)


@dataclass(eq=False)
class Voice(Taggable, Shelved):
    TAG_LIMIT: ClassVar[int | None] = MAX_TAGS_PER_ITEM

    file_path: str
    duration_ms: int = 0
    format: str = ""
    imported_at: datetime = field(default_factory=utcnow)
    tag_ids: set[int] = field(default_factory=set)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    # Where the file was copied from ("" when the workspace did not copy it): the audio
    # folder must not offer that file again while it is the same file.
    source_path: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        self._check_tags()
        self.file_path = ensure_non_empty(self.file_path, "Voice file path")
        self.duration_ms = ensure_non_negative(self.duration_ms, "duration_ms")
        self.format = self.format.lower().lstrip(".")


@dataclass(eq=False)
class IdeaNote(Taggable, Shelved):
    TAG_LIMIT: ClassVar[int | None] = MAX_TAGS_PER_ITEM

    text: str
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    tag_ids: set[int] = field(default_factory=set)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
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


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(eq=False)
class Transcript:
    """Machine transcript of one Voice (at most one per voice; re-running replaces it).

    Kept apart from TimestampNote: notes are the user's words, this is the recording's.
    """

    voice_id: int
    segments: list[TranscriptSegment]
    language: str = "fa"
    model: str = ""
    created_at: datetime = field(default_factory=utcnow)
    id: int | None = None

    def __post_init__(self) -> None:
        cleaned: list[TranscriptSegment] = []
        for seg in self.segments:
            text = normalize_persian(" ".join(seg.text.split()))
            if not text:
                continue
            start = ensure_non_negative(seg.start_ms, "start_ms")
            cleaned.append(TranscriptSegment(start, max(start, seg.end_ms), text))
        self.segments = sorted(cleaned, key=lambda s: s.start_ms)

    @property
    def text(self) -> str:
        return "\n".join(seg.text for seg in self.segments)
