"""flat tags: drop tags.parent_id

Revision ID: a9e2d5c8f314
Revises: f3a8c1e5d907
Create Date: 2026-09-22 10:00:00

SQLite refuses DROP COLUMN on a column inside a foreign key, so the table is rebuilt the
way SQLite documents it: copy, drop, rename. Migrations run with foreign keys off
(`db.migration_connection`), so dropping the old table cascades into nothing and the link
tables keep pointing at the name "tags". Ids are kept, so the search index rows stay
valid; its triggers went with the old table and are recreated (shape from a7f3c2d91e10).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9e2d5c8f314"
down_revision: str | None = "f3a8c1e5d907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = 5
INDEXES = ("search_word", "search_sub")


def _insert(index: str) -> str:
    return (
        f"INSERT INTO {index}(rowid, title, body) VALUES "
        f"(NEW.id * 8 + {KIND}, pw_norm(NEW.name), pw_norm(''));"
    )


def _delete(index: str) -> str:
    return f"DELETE FROM {index} WHERE rowid = OLD.id * 8 + {KIND};"


def _create_triggers() -> None:
    inserts = " ".join(_insert(ix) for ix in INDEXES)
    deletes = " ".join(_delete(ix) for ix in INDEXES)
    op.execute(f"CREATE TRIGGER tags_search_ai AFTER INSERT ON tags BEGIN {inserts} END")
    op.execute(f"CREATE TRIGGER tags_search_ad AFTER DELETE ON tags BEGIN {deletes} END")
    op.execute(f"CREATE TRIGGER tags_search_au AFTER UPDATE ON tags BEGIN {deletes} {inserts} END")


def upgrade() -> None:
    op.execute(
        "CREATE TABLE _tags_new ("
        "id INTEGER NOT NULL, "
        "name VARCHAR(64) COLLATE NOCASE NOT NULL, "
        "color VARCHAR(7) NOT NULL, "
        "CONSTRAINT pk_tags PRIMARY KEY (id), "
        "CONSTRAINT uq_tags_name UNIQUE (name))"
    )
    op.execute("INSERT INTO _tags_new (id, name, color) SELECT id, name, color FROM tags")
    op.execute("DROP TABLE tags")  # takes its index and search triggers along
    op.execute("ALTER TABLE _tags_new RENAME TO tags")
    _create_triggers()


def downgrade() -> None:
    # The column comes back empty and without its self-reference.
    op.execute("ALTER TABLE tags ADD COLUMN parent_id INTEGER")
    op.execute("CREATE INDEX ix_tags_parent_id ON tags (parent_id)")
