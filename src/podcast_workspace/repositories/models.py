"""SQLAlchemy ORM rows. Never leave the repositories package; repos map them to domain entities."""

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite, always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC-aware values.")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _link_table(name: str, left: str, right: str) -> Table:
    return Table(
        name,
        Base.metadata,
        Column(
            f"{left}_id",
            ForeignKey(f"{left}s.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        Column(
            f"{right}_id",
            ForeignKey(f"{right}s.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )


episode_tags = _link_table("episode_tags", "episode", "tag")
voice_tags = _link_table("voice_tags", "voice", "tag")
idea_note_tags = _link_table("idea_note_tags", "idea_note", "tag")
episode_voices = _link_table("episode_voices", "episode", "voice")
episode_idea_notes = _link_table("episode_idea_notes", "episode", "idea_note")


class TagRow(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64, collation="NOCASE"), unique=True)
    color: Mapped[str] = mapped_column(String(7))


class SeasonRow(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EpisodeRow(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    next_action: Mapped[str] = mapped_column(Text, default="")
    # No foreign key on purpose (see migration b8d4e6f1a320); SeasonRepository keeps it valid.
    season_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # The publish checklist (migration c6e1a8f4b2d7): ticked steps, comma-separated, and
    # where it went, one place per line.
    publish_done: Mapped[str] = mapped_column(String(64), default="")
    published_where: Mapped[str] = mapped_column(Text, default="")

    tags: Mapped[list[TagRow]] = relationship(secondary=episode_tags)
    voices: Mapped[list["VoiceRow"]] = relationship(secondary=episode_voices)
    idea_notes: Mapped[list["IdeaNoteRow"]] = relationship(secondary=episode_idea_notes)


class VoiceRow(Base):
    __tablename__ = "voices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, unique=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String(16), default="")
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Archive / trash (migration d2c7f9a4b615): plain nullable columns, None = not.
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    tags: Mapped[list[TagRow]] = relationship(secondary=voice_tags)


class IdeaNoteRow(Base):
    __tablename__ = "idea_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    tags: Mapped[list[TagRow]] = relationship(secondary=idea_note_tags)


class TimestampNoteRow(Base):
    __tablename__ = "timestamp_notes"
    __table_args__ = (Index("ix_timestamp_notes_voice_position", "voice_id", "position_ms"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voice_id: Mapped[int] = mapped_column(ForeignKey("voices.id", ondelete="CASCADE"))
    position_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EpisodeNoteRow(Base):
    __tablename__ = "episode_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TranscriptRow(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voice_id: Mapped[int] = mapped_column(ForeignKey("voices.id", ondelete="CASCADE"), unique=True)
    language: Mapped[str] = mapped_column(String(8), default="fa")
    model: Mapped[str] = mapped_column(String(64), default="")
    text: Mapped[str] = mapped_column(Text, default="")  # joined segments; what FTS indexes
    segments: Mapped[str] = mapped_column(Text, default="[]")  # JSON [[start, end, text], ...]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON-encoded
