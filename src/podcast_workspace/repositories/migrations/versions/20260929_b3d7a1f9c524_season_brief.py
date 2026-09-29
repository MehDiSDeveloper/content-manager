"""a season's brief: what it is about, and how it is laid out

Revision ID: b3d7a1f9c524
Revises: e8b3f1c6a492
Create Date: 2026-09-29 10:00:00

Two plain text columns on `seasons`, empty for the seasons that already exist.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3d7a1f9c524"
down_revision: str | None = "e8b3f1c6a492"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE seasons ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE seasons ADD COLUMN outline TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE seasons DROP COLUMN outline")
    op.execute("ALTER TABLE seasons DROP COLUMN summary")
