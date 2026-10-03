"""Concrete repositories, one per aggregate. They accept and return domain entities only."""

import json
from dataclasses import dataclass
from datetime import datetime
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
from podcast_workspace.domain.publish import PublishChecklist, PublishStep
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM, ensure_tag_limit
from podcast_workspace.domain.script_brief import ScriptBrief
from podcast_workspace.domain.smart_links import LinkKind
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
    episode_idea_notes,
    episode_voices,
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
        return Tag(name=row.name, color=row.color, id=row.id)

    def _apply(self, entity: Tag, row: TagRow) -> None:
        row.name = entity.name
        row.color = entity.color

    def list_all(self) -> list[Tag]:
        rows = self.session.scalars(select(TagRow).order_by(TagRow.name))
        return [self._to_domain(row) for row in rows]

    def find_by_name(self, name: str) -> Tag | None:
        row = self.session.scalar(select(TagRow).where(TagRow.name == name))
        return None if row is None else self._to_domain(row)

    def usage_counts(self) -> dict[int, int]:
        """Tag id -> number of episodes, voices and ideas carrying it. Items in the trash
        do not count: they are nowhere else in the app either."""
        rows = self.session.execute(
            text(
                "SELECT tag_id, COUNT(*) FROM ("
                " SELECT tag_id FROM episode_tags UNION ALL"
                " SELECT tag_id FROM voice_tags WHERE voice_id NOT IN"
                "  (SELECT id FROM voices WHERE deleted_at IS NOT NULL) UNION ALL"
                " SELECT tag_id FROM idea_note_tags WHERE idea_note_id NOT IN"
                "  (SELECT id FROM idea_notes WHERE deleted_at IS NOT NULL)"
                ") GROUP BY tag_id"
            )
        )
        return {tag_id: count for tag_id, count in rows}

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

    def merge_into(self, source_id: int, target_id: int) -> None:
        """Move every use of `source` onto `target`, then delete `source`.

        Never grows an item's tag count (an item holding both ends with one), so the
        15-tag limit cannot be violated by a merge.
        """
        if source_id == target_id:
            return
        self._row(source_id)  # both must exist
        self._row(target_id)
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
            publish=PublishChecklist(
                frozenset(PublishStep(s) for s in row.publish_done.split(",") if s),
                row.published_where,
            ),
            brief=ScriptBrief.from_dict(json.loads(row.script_brief or "{}")),
            summary=row.summary,
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
        # Stored in the enum's order, so the same checklist is always the same text.
        row.publish_done = ",".join(s.value for s in PublishStep if s in entity.publish.done)
        row.published_where = entity.publish.where
        row.script_brief = json.dumps(entity.brief.to_dict(), ensure_ascii=False)
        row.summary = entity.summary
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

    def list_all(self) -> list[Episode]:
        rows = self.session.scalars(select(EpisodeRow).order_by(EpisodeRow.updated_at.desc()))
        return [self._to_domain(row) for row in rows]

    def link_counts(self) -> dict[tuple[LinkKind, int], int]:
        """How many episodes each voice / idea is linked to (only the linked ones)."""
        counts: dict[tuple[LinkKind, int], int] = {}
        for kind, table, column in (
            (LinkKind.VOICE, episode_voices, episode_voices.c.voice_id),
            (LinkKind.IDEA, episode_idea_notes, episode_idea_notes.c.idea_note_id),
        ):
            query = select(column, func.count()).select_from(table).group_by(column)
            for item_id, n in self.session.execute(query):
                counts[(kind, item_id)] = n
        return counts

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
        return Season(
            id=row.id,
            title=row.title,
            readme=row.readme,
            about=row.about,
            created_at=row.created_at,
        )

    def _apply(self, entity: Season, row: SeasonRow) -> None:
        row.title = entity.title
        row.readme = entity.readme
        row.about = entity.about
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
            archived_at=row.archived_at,
            deleted_at=row.deleted_at,
            source_path=row.source_path or "",
        )

    def _apply(self, entity: Voice, row: VoiceRow) -> None:
        # Re-check at the persistence boundary: tag_ids may have been mutated in place.
        ensure_tag_limit(entity.tag_ids, Voice.TAG_LIMIT or 0)
        row.file_path = entity.file_path
        row.duration_ms = entity.duration_ms
        row.format = entity.format
        row.imported_at = entity.imported_at
        row.archived_at = entity.archived_at
        row.deleted_at = entity.deleted_at
        row.source_path = entity.source_path
        row.tags = self._tag_rows(entity.tag_ids)

    def find_by_path(self, file_path: str) -> Voice | None:
        row = self.session.scalar(select(VoiceRow).where(VoiceRow.file_path == file_path))
        return None if row is None else self._to_domain(row)

    def list_all(self, include_trashed: bool = False) -> list[Voice]:
        """Newest first. The trash is left out unless asked for (export, the audio
        folder's "already known" check, restoring links)."""
        query = select(VoiceRow).order_by(VoiceRow.imported_at.desc())
        if not include_trashed:
            query = query.where(VoiceRow.deleted_at.is_(None))
        return [self._to_domain(row) for row in self.session.scalars(query)]

    def list_trashed(self) -> list[Voice]:
        query = select(VoiceRow).where(VoiceRow.deleted_at.is_not(None))
        return [self._to_domain(row) for row in self.session.scalars(query)]

    def ids_trashed_before(self, cutoff: datetime) -> set[int]:
        query = select(VoiceRow.id).where(VoiceRow.deleted_at <= cutoff)
        return set(self.session.scalars(query))


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
            archived_at=row.archived_at,
            deleted_at=row.deleted_at,
        )

    def _apply(self, entity: IdeaNote, row: IdeaNoteRow) -> None:
        ensure_tag_limit(entity.tag_ids, IdeaNote.TAG_LIMIT or 0)
        row.text = entity.text
        row.created_at = entity.created_at
        row.updated_at = entity.updated_at
        row.archived_at = entity.archived_at
        row.deleted_at = entity.deleted_at
        row.tags = self._tag_rows(entity.tag_ids)

    def list_all(self, include_trashed: bool = False) -> list[IdeaNote]:
        query = select(IdeaNoteRow).order_by(IdeaNoteRow.updated_at.desc())
        if not include_trashed:
            query = query.where(IdeaNoteRow.deleted_at.is_(None))
        return [self._to_domain(row) for row in self.session.scalars(query)]

    def list_trashed(self) -> list[IdeaNote]:
        query = select(IdeaNoteRow).where(IdeaNoteRow.deleted_at.is_not(None))
        return [self._to_domain(row) for row in self.session.scalars(query)]

    def ids_trashed_before(self, cutoff: datetime) -> set[int]:
        query = select(IdeaNoteRow.id).where(IdeaNoteRow.deleted_at <= cutoff)
        return set(self.session.scalars(query))


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

    def texts_by_voice(self) -> dict[int, str]:
        """Voice id -> its notes' text in playback order, one per line (for searches)."""
        rows = self.session.execute(
            select(TimestampNoteRow.voice_id, TimestampNoteRow.text).order_by(
                TimestampNoteRow.voice_id, TimestampNoteRow.position_ms, TimestampNoteRow.id
            )
        )
        texts: dict[int, list[str]] = {}
        for voice_id, note in rows:
            texts.setdefault(voice_id, []).append(note)
        return {voice_id: "\n".join(notes) for voice_id, notes in texts.items()}


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

    def texts(self) -> dict[int, str]:
        """voice id -> transcript text, without the segments (for list searches)."""
        rows = self.session.execute(select(TranscriptRow.voice_id, TranscriptRow.text))
        return {voice_id: text for voice_id, text in rows}

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
