"""the publish checklist of an episode

Revision ID: c6e1a8f4b2d7
Revises: a9e2d5c8f314
Create Date: 2026-09-28 10:00:00

Two plain columns on `episodes`, added with ALTER TABLE rather than a batch rebuild: a
rebuild drops the old table, and under foreign_keys=ON that cascades through every tag
link, note and voice/idea link of every episode (see b8d4e6f1a320). The FTS triggers on
`episodes` are left alone by an ADD COLUMN.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c6e1a8f4b2d7"
down_revision: str | None = "a9e2d5c8f314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE episodes ADD COLUMN publish_done VARCHAR(64) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE episodes ADD COLUMN published_where TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE episodes DROP COLUMN published_where")
    op.execute("ALTER TABLE episodes DROP COLUMN publish_done")
