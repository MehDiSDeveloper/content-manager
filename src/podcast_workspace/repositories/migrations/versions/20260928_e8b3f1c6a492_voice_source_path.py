"""where a stored voice was copied from

Revision ID: e8b3f1c6a492
Revises: c6e1a8f4b2d7
Create Date: 2026-09-28 18:00:00

Added audio is now copied into the workspace's own folder, so clearing the recorder's
folder loses nothing. `source_path` remembers the original, which the audio folder uses to
keep from offering a file that is already in. ALTER TABLE, not a batch rebuild: a rebuild
would cascade through every tag link, note, transcript and episode link of every voice
(see c6e1a8f4b2d7); the FTS triggers on `voices` are left alone by an ADD COLUMN.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8b3f1c6a492"
down_revision: str | None = "c6e1a8f4b2d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE voices ADD COLUMN source_path TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE voices DROP COLUMN source_path")
