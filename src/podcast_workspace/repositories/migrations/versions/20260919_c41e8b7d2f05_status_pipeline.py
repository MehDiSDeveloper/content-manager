"""episode status pipeline: idea, outline, recorded, script_ready, edited, published

Revision ID: c41e8b7d2f05
Revises: a7f3c2d91e10
Create Date: 2026-09-19 21:00:00

Data-only migration (status is a plain String column). "archived" has no place in the new
pipeline and becomes "published", the closest finished state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41e8b7d2f05"
down_revision: str | None = "a7f3c2d91e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FORWARD = {
    "outlining": "outline",
    "recording": "recorded",
    "editing": "edited",
    "archived": "published",
}
BACKWARD = {
    "outline": "outlining",
    "recorded": "recording",
    "script_ready": "recording",
    "edited": "editing",
}


def _remap(mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(
            sa.text("UPDATE episodes SET status = :new WHERE status = :old").bindparams(
                new=new, old=old
            )
        )


def upgrade() -> None:
    _remap(FORWARD)


def downgrade() -> None:
    _remap(BACKWARD)
