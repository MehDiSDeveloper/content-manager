"""archive and trash for voices and ideas

Revision ID: d2c7f9a4b615
Revises: b8d4e6f1a320
Create Date: 2026-09-21 18:00:00

Two nullable timestamps on `voices` and `idea_notes`, added with a plain ALTER TABLE:
a batch rebuild of either table would drop it under foreign_keys=ON and cascade away
every tag link, timestamp note, transcript and episode link (see b8d4e6f1a320).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2c7f9a4b615"
down_revision: str | None = "b8d4e6f1a320"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("voices", "idea_notes")
_COLUMNS = ("archived_at", "deleted_at")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} DATETIME")


def downgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
