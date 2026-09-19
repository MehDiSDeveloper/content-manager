"""voice transcripts (one per voice), indexed in both FTS tables as kind 7

Revision ID: e5a91d3c7b28
Revises: c41e8b7d2f05
Create Date: 2026-09-20 10:00:00

Trigger shape copied from a7f3c2d91e10 (migrations must not import each other).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a91d3c7b28"
down_revision: str | None = "c41e8b7d2f05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = 7
INDEXES = ("search_word", "search_sub")


def _insert(index: str, r: str) -> str:
    return (
        f"INSERT INTO {index}(rowid, title, body) VALUES "
        f"({r}.id * 8 + {KIND}, pw_norm(''), pw_norm({r}.text));"
    )


def _delete(index: str) -> str:
    return f"DELETE FROM {index} WHERE rowid = OLD.id * 8 + {KIND};"


def upgrade() -> None:
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segments", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voices.id"],
            name=op.f("fk_transcripts_voice_id_voices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcripts")),
        sa.UniqueConstraint("voice_id", name=op.f("uq_transcripts_voice_id")),
    )
    inserts = " ".join(_insert(ix, "NEW") for ix in INDEXES)
    deletes = " ".join(_delete(ix) for ix in INDEXES)
    op.execute(f"CREATE TRIGGER transcripts_search_ai AFTER INSERT ON transcripts BEGIN {inserts} END")
    op.execute(f"CREATE TRIGGER transcripts_search_ad AFTER DELETE ON transcripts BEGIN {deletes} END")
    op.execute(
        f"CREATE TRIGGER transcripts_search_au AFTER UPDATE ON transcripts "
        f"BEGIN {deletes} {inserts} END"
    )


def downgrade() -> None:
    for suffix in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER IF EXISTS transcripts_search_{suffix}")
    op.execute(f"DELETE FROM search_word WHERE rowid % 8 = {KIND}")
    op.execute(f"DELETE FROM search_sub WHERE rowid % 8 = {KIND}")
    op.drop_table("transcripts")
