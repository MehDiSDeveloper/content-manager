"""Concrete repositories, one per aggregate. They accept and return domain entities only."""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text

from podcast_workspace.domain.entities import (
    Episode,
    EpisodeNote,
    EpisodeStatus,
    IdeaNote,
    Season,
    Tag,
    TimestampNote,
    Transcript,
    TranscriptSegment,
    Voice,
)
from podcast_workspace.domain.errors import NotFoundError
from podcast_workspace.domain.rules import (
    MAX_TAGS_PER_ITEM,
    ensure_tag_limit,
    ensure_valid_parent,
)
from podcast_workspace.repositories.base import SqlRepository
from podcast_workspace.repositories.models import (
    EpisodeNoteRow,
    EpisodeRow,
    IdeaNoteRow,
    SeasonRow,
    SettingRow,
    TagRow,
    TimestampNoteRow,
    TranscriptRow,
    VoiceRow,
)


@dataclass(frozen=True)
class TagUses:
    """Everything one tag is attached to. Small (ids only): safe to keep in an undo entry."""

    episodes: frozenset[int] = frozenset()
    voices: frozenset[int] = frozenset()
    ideas: frozenset[int] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.episodes or self.voices or self.ideas)

    def __len__(self) -> int:
        return len(self.episodes) + len(self.voices) + len(self.ideas)


# link table, its item column, its owning table, and the tag limit of that item kind
_USE_TABLES = (
    ("episodes", "episode_tags", "episode_id", None),
    ("voices", "voice_tags", "voice_id", MAX_TAGS_PER_ITEM),
    ("idea_notes", "idea_note_tags", "idea_note_id", MAX_TAGS_PER_ITEM),
)


class TagRepository(SqlRepository[Tag, TagRow]):
    row_type = TagRow
    entity_name = "Tag"

    def _to_domain(self, row: TagRow) -> Tag:
        return Tag(name=row.name, color=row.color, parent_id=row.parent_id, id=row.id)

    def _apply(self, entity: Tag, row: TagRow) -> None:
        if entity.parent_id is not None:
            self._row(entity.parent_id)
        ensure_valid_parent(entity.id, entity.parent_id, self._parent_of)
        row.name = entity.name
        row.color = entity.color
        row.parent_id = entity.parent_id

    def _parent_of(self, tag_id: int) -> int | None:
        return self.session.scalar(select(TagRow.parent_id).where(TagRow.id == tag_id))

    def list_all(self) -> list[Tag]:
        rows = self.session.scalars(select(TagRow).order_by(TagRow.name))
        return [self._to_domain(row) for row in rows]

    def find_by_name(self, name: str) -> Tag | None:
        row = self.session.scalar(select(TagRow).where(TagRow.name == name))
        return None if row is None else self._to_domain(row)

    def children_of(self, tag_id: int | None) -> list[Tag]:
        condition = TagRow.parent_id.is_(None) if tag_id is None else TagRow.parent_id == tag_id
        rows = self.session.scalars(select(TagRow).where(condition).order_by(TagRow.name))
        return [self._to_domain(row) for row in rows]

    def usage_counts(self) -> dict[int, int]:
        """Tag id -> number of episodes, voices and ideas carrying it."""
        rows = self.session.execute(
            text(
                "SELECT tag_id, COUNT(*) FROM ("
                " SELECT tag_id FROM episode_tags UNION ALL"
                " SELECT tag_id FROM voice_tags UNION ALL"
                " SELECT tag_id FROM idea_note_tags) GROUP BY tag_id"
            )
        )
        return {tag_id: count for tag_id, count in rows}

    def child_ids(self, tag_id: int) -> set[int]:
        return set(self.session.scalars(select(TagRow.id).where(TagRow.parent_id == tag_id)))

    def reparent(self, tag_ids: set[int], parent_id: int | None) -> None:
        """Put a set of tags under one parent (used to undo a delete or a merge)."""
        for tag_id in tag_ids:
            row = self.session.get(TagRow, tag_id)
            if row is not None:
                row.parent_id = parent_id
        self.session.flush()

    def uses_of(self, tag_id: int) -> TagUses:
        """What carries this tag right now."""
        found: dict[str, frozenset[int]] = {}
        for owner, table, column, _limit in _USE_TABLES:
            rows = self.session.execute(
                text(f"SELECT {column} FROM {table} WHERE tag_id = :tag"), {"tag": tag_id}
            )
            found[owner] = frozenset(item_id for (item_id,) in rows)
        return TagUses(found["episodes"], found["voices"], found["idea_notes"])

    def add_uses(self, tag_id: int, uses: TagUses) -> None:
        """Re-attach a tag to the items that had it. Items that filled up their tags in
        the meantime are skipped: the 15-tag limit outranks putting a use back."""
        for ids, (owner, table, column, limit) in zip(
            (uses.episodes, uses.voices, uses.ideas), _USE_TABLES, strict=True
        ):
            for item_id in ids:
                room = (
                    ""
                    if limit is None
                    else f" AND (SELECT COUNT(*) FROM {table} WHERE {column} = :item) < {limit}"
                )
                self.session.execute(
                    text(
                        f"INSERT OR IGNORE INTO {table} ({column}, tag_id) SELECT :item, :tag "
                        f"WHERE EXISTS (SELECT 1 FROM {owner} WHERE id = :item){room}"
                    ),
                    {"item": item_id, "tag": tag_id},
                )
        self.session.expire_all()

    def remove_uses(self, tag_id: int, uses: TagUses) -> None:
        for ids, (_owner, table, column, _limit) in zip(
            (uses.episodes, uses.voices, uses.ideas), _USE_TABLES, strict=True
        ):
            for item_id in ids:
                self.session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :item AND tag_id = :tag"),
                    {"item": item_id, "tag": tag_id},
                )
        self.session.expire_all()

    def delete_keeping_children(self, tag_id: int) -> None:
        """Delete a tag; its children move up to its parent instead of becoming roots."""
        parent_id = self._row(tag_id).parent_id
        self.session.execute(
            text("UPDATE tags SET parent_id = :parent WHERE parent_id = :tag"),
            {"parent": parent_id, "tag": tag_id},
        )
        self.session.expire_all()
        self.delete(tag_id)

    def merge_into(self, source_id: int, target_id: int) -> None:
        """Move every use of `source` onto `target`, then delete `source`.

        Never grows an item's tag count (an item holding both ends with one), so the
        15-tag limit cannot be violated by a merge.
        """
        if source_id == target_id:
            return
        source, target = self._row(source_id), self._row(target_id)
        params = {"source": source_id, "target": target_id}
        for table, column in (
            ("episode_tags", "episode_id"),
            ("voice_tags", "voice_id"),
            ("idea_note_tags", "idea_note_id"),
        ):
            self.session.execute(
                text(
                    f"INSERT OR IGNORE INTO {table} ({column}, tag_id) "
                    f"SELECT {column}, :target FROM {table} WHERE tag_id = :source"
                ),
                params,
            )
        self.session.execute(
            text("UPDATE tags SET parent_id = :target WHERE parent_id = :source AND id != :target"),
            params,
        )
        if target.parent_id == source_id:  # target nested under source: lift it one level
            self.session.execute(
                text("UPDATE tags SET parent_id = :parent WHERE id = :target"),
                {"parent": source.parent_id, "target": target_id},
            )
        self.session.expire_all()
        self.delete(source_id)


class EpisodeRepository(SqlRepository[Episode, EpisodeRow]):
    row_type = EpisodeRow
    entity_name = "Episode"

    def _to_domain(self, row: EpisodeRow) -> Episode:
        return Episode(
            id=row.id,
            title=row.title,
            status=EpisodeStatus(row.status),
            next_action=row.next_action,
            season_id=row.season_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_opened_at=row.last_opened_at,
            tag_ids={tag.id for tag in row.tags},
            voice_ids={voice.id for voice in row.voices},
            idea_note_ids={idea.id for idea in row.idea_notes},
        )

    def _apply(self, entity: Episode, row: EpisodeRow) -> None:
        row.title = entity.title
        row.status = entity.status.value
        row.next_action = entity.next_action
        if entity.season_id is not None and self.session.get(SeasonRow, entity.season_id) is None:
            raise NotFoundError("Season", entity.season_id)
        row.season_id = entity.season_id
        row.created_at = entity.created_at
        row.updated_at = entity.updated_at
        row.last_opened_at = entity.last_opened_at
        row.tags = self._tag_rows(entity.tag_ids)
        row.voices = self._rows(VoiceRow, "Voice", entity.voice_ids)
        row.idea_notes = self._rows(IdeaNoteRow, "IdeaNote", entity.idea_note_ids)

    def _rows[T: (VoiceRow, IdeaNoteRow)](
        self, row_type: type[T], name: str, ids: set[int]
    ) -> list[T]:
        if not ids:
            return []
        rows = list(self.session.scalars(select(row_type).where(row_type.id.in_(ids))))
        missing = ids - {row.id for row in rows}
        if missing:
            raise NotFoundError(name, min(missing))
        return rows

    def ids_with_voice(self, voice_id: int) -> set[int]:
        """Episodes this voice is linked to (the link rows vanish with the voice)."""
        return self._linked_ids("episode_voices", "voice_id", voice_id)

    def ids_with_idea(self, idea_id: int) -> set[int]:
        return self._linked_ids("episode_idea_notes", "idea_note_id", idea_id)

    def _linked_ids(self, table: str, column: str, item_id: int) -> set[int]:
        rows = self.session.execute(
            text(f"SELECT episode_id FROM {table} WHERE {column} = :item"), {"item": item_id}
        )
        return {episode_id for (episode_id,) in rows}

    def list_all(self) -> list[Episode]:
        rows = self.session.scalars(select(EpisodeRow).order_by(EpisodeRow.updated_at.desc()))
        return [self._to_domain(row) for row in rows]

    def ids_in_season(self, season_id: int) -> set[int]:
        query = select(EpisodeRow.id).where(EpisodeRow.season_id == season_id)
        return set(self.session.scalars(query))

    def move_to_season(self, episode_ids: set[int], season_id: int | None) -> None:
        """Put episodes into a season (or none) without touching them: filing is not editing."""
        for episode_id in episode_ids:
            row = self.session.get(EpisodeRow, episode_id)
            if row is not None:
                row.season_id = season_id
        self.session.flush()


class SeasonRepository(SqlRepository[Season, SeasonRow]):
    row_type = SeasonRow
    entity_name = "Season"

    def _to_domain(self, row: SeasonRow) -> Season:
        return Season(id=row.id, title=row.title, created_at=row.created_at)

    def _apply(self, entity: Season, row: SeasonRow) -> None:
        row.title = entity.title
        row.created_at = entity.created_at

    def delete(self, entity_id: int) -> None:
        """The season goes; its episodes stay, belonging to no season.

        Done here rather than by the database: `episodes.season_id` has no foreign key
        (migration b8d4e6f1a320 says why).
        """
        row = self._row(entity_id)
        self.session.execute(
            text("UPDATE episodes SET season_id = NULL WHERE season_id = :season"),
            {"season": entity_id},
        )
        self.session.delete(row)
        self.session.flush()
        self.session.expire_all()


class VoiceRepository(SqlRepository[Voice, VoiceRow]):
    row_type = VoiceRow
    entity_name = "Voice"

    def _to_domain(self, row: VoiceRow) -> Voice:
        return Voice(
            id=row.id,
            file_path=row.file_path,
            duration_ms=row.duration_ms,
            format=row.format,
            imported_at=row.imported_at,
            tag_ids={tag.id for tag in row.tags},
        )

    def _apply(self, entity: Voice, row: VoiceRow) -> None:
        # Re-check at the persistence boundary: tag_ids may have been mutated in place.
        ensure_tag_limit(entity.tag_ids, Voice.TAG_LIMIT or 0)
        row.file_path = entity.file_path
        row.duration_ms = entity.duration_ms
        row.format = entity.format
        row.imported_at = entity.imported_at
        row.tags = self._tag_rows(entity.tag_ids)

    def find_by_path(self, file_path: str) -> Voice | None:
        row = self.session.scalar(select(VoiceRow).where(VoiceRow.file_path == file_path))
        return None if row is None else self._to_domain(row)

    def list_all(self) -> list[Voice]:
        rows = self.session.scalars(select(VoiceRow).order_by(VoiceRow.imported_at.desc()))
        return [self._to_domain(row) for row in rows]


class IdeaNoteRepository(SqlRepository[IdeaNote, IdeaNoteRow]):
    row_type = IdeaNoteRow
    entity_name = "IdeaNote"

    def _to_domain(self, row: IdeaNoteRow) -> IdeaNote:
        return IdeaNote(
            id=row.id,
            text=row.text,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tag_ids={tag.id for tag in row.tags},
        )

    def _apply(self, entity: IdeaNote, row: IdeaNoteRow) -> None:
        ensure_tag_limit(entity.tag_ids, IdeaNote.TAG_LIMIT or 0)
        row.text = entity.text
        row.created_at = entity.created_at
        row.updated_at = entity.updated_at
        row.tags = self._tag_rows(entity.tag_ids)

    def list_all(self) -> list[IdeaNote]:
        rows = self.session.scalars(select(IdeaNoteRow).order_by(IdeaNoteRow.updated_at.desc()))
        return [self._to_domain(row) for row in rows]


class TimestampNoteRepository(SqlRepository[TimestampNote, TimestampNoteRow]):
    row_type = TimestampNoteRow
    entity_name = "TimestampNote"

    def _to_domain(self, row: TimestampNoteRow) -> TimestampNote:
        return TimestampNote(
            id=row.id,
            voice_id=row.voice_id,
            position_ms=row.position_ms,
            text=row.text,
            created_at=row.created_at,
        )

    def _apply(self, entity: TimestampNote, row: TimestampNoteRow) -> None:
        row.voice_id = entity.voice_id
        row.position_ms = entity.position_ms
        row.text = entity.text
        row.created_at = entity.created_at

    def list_for_voice(self, voice_id: int) -> list[TimestampNote]:
        rows = self.session.scalars(
            select(TimestampNoteRow)
            .where(TimestampNoteRow.voice_id == voice_id)
            .order_by(TimestampNoteRow.position_ms)
        )
        return [self._to_domain(row) for row in rows]

    def counts_by_voice(self) -> dict[int, int]:
        """Voice id -> number of timestamp notes, for list subtitles (one query)."""
        rows = self.session.execute(
            select(TimestampNoteRow.voice_id, func.count(TimestampNoteRow.id)).group_by(
                TimestampNoteRow.voice_id
            )
        )
        return {voice_id: count for voice_id, count in rows}


class EpisodeNoteRepository(SqlRepository[EpisodeNote, EpisodeNoteRow]):
    row_type = EpisodeNoteRow
    entity_name = "EpisodeNote"

    def _to_domain(self, row: EpisodeNoteRow) -> EpisodeNote:
        return EpisodeNote(
            id=row.id,
            episode_id=row.episode_id,
            title=row.title,
            body=row.body,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _apply(self, entity: EpisodeNote, row: EpisodeNoteRow) -> None:
        row.episode_id = entity.episode_id
        row.title = entity.title
        row.body = entity.body
        row.created_at = entity.created_at
        row.updated_at = entity.updated_at

    def list_for_episode(self, episode_id: int) -> list[EpisodeNote]:
        rows = self.session.scalars(
            select(EpisodeNoteRow)
            .where(EpisodeNoteRow.episode_id == episode_id)
            .order_by(EpisodeNoteRow.created_at)
        )
        return [self._to_domain(row) for row in rows]


class TranscriptRepository(SqlRepository[Transcript, TranscriptRow]):
    row_type = TranscriptRow
    entity_name = "Transcript"

    def _to_domain(self, row: TranscriptRow) -> Transcript:
        return Transcript(
            id=row.id,
            voice_id=row.voice_id,
            language=row.language,
            model=row.model,
            created_at=row.created_at,
            segments=[TranscriptSegment(a, b, t) for a, b, t in json.loads(row.segments)],
        )

    def _apply(self, entity: Transcript, row: TranscriptRow) -> None:
        row.voice_id = entity.voice_id
        row.language = entity.language
        row.model = entity.model
        row.created_at = entity.created_at
        row.text = entity.text
        row.segments = json.dumps(
            [[s.start_ms, s.end_ms, s.text] for s in entity.segments], ensure_ascii=False
        )

    def for_voice(self, voice_id: int) -> Transcript | None:
        row = self.session.scalar(select(TranscriptRow).where(TranscriptRow.voice_id == voice_id))
        return None if row is None else self._to_domain(row)

    def voice_ids(self) -> set[int]:
        return set(self.session.scalars(select(TranscriptRow.voice_id)))

    def replace(self, transcript: Transcript) -> Transcript:
        """Store as the voice's only transcript (the old one, if any, is dropped)."""
        row = self.session.scalar(
            select(TranscriptRow).where(TranscriptRow.voice_id == transcript.voice_id)
        )
        if row is not None:
            self.session.delete(row)
            self.session.flush()
        transcript.id = None
        return self.add(transcript)


class SettingsRepository:
    """Key/value store; values are JSON-encoded."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def get(self, key: str, default: Any = None) -> Any:
        row = self.session.get(SettingRow, key)
        return default if row is None else json.loads(row.value)

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        row = self.session.get(SettingRow, key)
        if row is None:
            self.session.add(SettingRow(key=key, value=encoded))
        else:
            row.value = encoded
        self.session.flush()

    def all(self) -> dict[str, Any]:
        rows = self.session.scalars(select(SettingRow))
        return {row.key: json.loads(row.value) for row in rows}
