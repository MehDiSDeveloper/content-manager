"""a number for each season and episode

Revision ID: f5c2a8d1e7b4
Revises: e1b7c4a9f2d6
Create Date: 2026-10-03 20:00:00

Their order, given by hand: an episode made early can say it is the third. Nullable
(not numbered yet); plain ALTER TABLEs, as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f5c2a8d1e7b4"
down_revision: str | None = "e1b7c4a9f2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE seasons ADD COLUMN number INTEGER")
    op.execute("ALTER TABLE episodes ADD COLUMN number INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE episodes DROP COLUMN number")
    op.execute("ALTER TABLE seasons DROP COLUMN number")
