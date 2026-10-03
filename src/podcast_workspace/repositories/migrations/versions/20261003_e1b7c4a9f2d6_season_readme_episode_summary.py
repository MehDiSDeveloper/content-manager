"""a season's readme and about; an episode's summary

Revision ID: e1b7c4a9f2d6
Revises: d4f2b8e6a1c3
Create Date: 2026-10-03 18:00:00

The season brief becomes the producer's readme (what `summary` held, with the old
`outline` appended under it: both were the producer's plan) beside an `about` for
listeners. Episodes get a `summary` of what they said. Plain ALTER TABLEs, as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1b7c4a9f2d6"
down_revision: str | None = "d4f2b8e6a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE seasons RENAME COLUMN summary TO readme")
    op.execute(
        "UPDATE seasons SET readme = CASE WHEN readme = '' THEN outline "
        "ELSE readme || char(10) || char(10) || outline END WHERE outline != ''"
    )
    op.execute("ALTER TABLE seasons DROP COLUMN outline")
    op.execute("ALTER TABLE seasons ADD COLUMN about TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE episodes ADD COLUMN summary TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE episodes DROP COLUMN summary")
    op.execute("ALTER TABLE seasons DROP COLUMN about")
    op.execute("ALTER TABLE seasons ADD COLUMN outline TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE seasons RENAME COLUMN readme TO summary")
