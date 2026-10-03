"""an episode's script brief

Revision ID: d4f2b8e6a1c3
Revises: b3d7a1f9c524
Create Date: 2026-10-03 10:00:00

One text column on `episodes` holding the brief as JSON (`ScriptBrief.to_dict`); empty
means the defaults. ALTER TABLE, not a batch rebuild (see c6e1a8f4b2d7).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4f2b8e6a1c3"
down_revision: str | None = "b3d7a1f9c524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE episodes ADD COLUMN script_brief TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE episodes DROP COLUMN script_brief")
