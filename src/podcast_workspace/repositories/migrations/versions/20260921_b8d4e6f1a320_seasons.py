"""seasons, and the season an episode belongs to

Revision ID: b8d4e6f1a320
Revises: e5a91d3c7b28
Create Date: 2026-09-21 10:00:00

`episodes.season_id` is added with a plain ALTER TABLE and carries no foreign key. Adding
one means a batch rebuild of `episodes`, and dropping the old table under
foreign_keys=ON cascades: every tag link, note and voice/idea link of every episode
goes with it. The repositories keep the column honest instead (a season must exist to
be assigned; deleting a season empties it first).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4e6f1a320"
down_revision: str | None = "e5a91d3c7b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seasons")),
    )
    op.execute("ALTER TABLE episodes ADD COLUMN season_id INTEGER")
    op.create_index(op.f("ix_episodes_season_id"), "episodes", ["season_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_episodes_season_id"), table_name="episodes")
    op.execute("ALTER TABLE episodes DROP COLUMN season_id")
    op.drop_table("seasons")
