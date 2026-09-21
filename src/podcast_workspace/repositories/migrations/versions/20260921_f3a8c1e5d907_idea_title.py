"""index an idea's first line as its title

Revision ID: f3a8c1e5d907
Revises: d2c7f9a4b615
Create Date: 2026-09-21 21:00:00

Search can leave the content out and read titles only; an idea has no title of its own,
so its first line (what the lists show as its title) goes in the title column. The body
keeps the whole text. Trigger shape copied from a7f3c2d91e10.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a8c1e5d907"
down_revision: str | None = "d2c7f9a4b615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = 2
INDEXES = ("search_word", "search_sub")
# Keep in step with _SOURCE_SQL in repositories/search_repo.py.
_LEAD = "ltrim({r}.text, ' ' || char(9, 10, 13))"
FIRST_LINE = f"substr({_LEAD}, 1, instr({_LEAD} || char(10), char(10)) - 1)"


def _insert(index: str, title: str, r: str) -> str:
    return (
        f"INSERT INTO {index}(rowid, title, body) VALUES "
        f"({r}.id * 8 + {KIND}, pw_norm({title.format(r=r)}), pw_norm({r}.text));"
    )


def _delete(index: str) -> str:
    return f"DELETE FROM {index} WHERE rowid = OLD.id * 8 + {KIND};"


def _rebuild(title: str) -> None:
    for suffix in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER IF EXISTS idea_notes_search_{suffix}")
    inserts = " ".join(_insert(ix, title, "NEW") for ix in INDEXES)
    deletes = " ".join(_delete(ix) for ix in INDEXES)
    op.execute(f"CREATE TRIGGER idea_notes_search_ai AFTER INSERT ON idea_notes BEGIN {inserts} END")
    op.execute(f"CREATE TRIGGER idea_notes_search_ad AFTER DELETE ON idea_notes BEGIN {deletes} END")
    op.execute(
        f"CREATE TRIGGER idea_notes_search_au AFTER UPDATE ON idea_notes "
        f"BEGIN {deletes} {inserts} END"
    )
    for index in INDEXES:
        op.execute(f"DELETE FROM {index} WHERE rowid % 8 = {KIND}")
        op.execute(
            f"INSERT INTO {index}(rowid, title, body) SELECT id * 8 + {KIND}, "
            f"pw_norm({title.format(r='idea_notes')}), pw_norm(text) FROM idea_notes"
        )


def upgrade() -> None:
    _rebuild(FIRST_LINE)


def downgrade() -> None:
    _rebuild("''")
