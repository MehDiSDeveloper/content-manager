"""full-text search index (FTS5 word + trigram) maintained by triggers

Revision ID: a7f3c2d91e10
Revises: 5c0bcd4c8144
Create Date: 2026-09-19 19:10:00

Triggers call pw_norm(), a SQL function registered on every connection by
repositories/db.py. Rowid = source_id * 8 + kind (see domain/search.py).
Batch-altering a source table recreates it and DROPS its triggers: re-run
_create_triggers for that table in the same migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7f3c2d91e10"
down_revision: str | None = "5c0bcd4c8144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> (kind, title expression, body expression); `{r}` is NEW/OLD or the table itself
SOURCES: dict[str, tuple[int, str, str]] = {
    "episodes": (1, "{r}.title", "{r}.next_action"),
    "idea_notes": (2, "''", "{r}.text"),
    "episode_notes": (3, "{r}.title", "{r}.body"),
    "timestamp_notes": (4, "''", "{r}.text"),
    "tags": (5, "{r}.name", "''"),
    "voices": (6, "{r}.file_path", "''"),
}
INDEXES = ("search_word", "search_sub")


def _insert(index: str, kind: int, title: str, body: str, r: str) -> str:
    return (
        f"INSERT INTO {index}(rowid, title, body) VALUES "
        f"({r}.id * 8 + {kind}, pw_norm({title.format(r=r)}), pw_norm({body.format(r=r)}));"
    )


def _delete(index: str, kind: int) -> str:
    return f"DELETE FROM {index} WHERE rowid = OLD.id * 8 + {kind};"


def _create_triggers(table: str) -> None:
    kind, title, body = SOURCES[table]
    inserts = " ".join(_insert(ix, kind, title, body, "NEW") for ix in INDEXES)
    deletes = " ".join(_delete(ix, kind) for ix in INDEXES)
    op.execute(f"CREATE TRIGGER {table}_search_ai AFTER INSERT ON {table} BEGIN {inserts} END")
    op.execute(f"CREATE TRIGGER {table}_search_ad AFTER DELETE ON {table} BEGIN {deletes} END")
    op.execute(
        f"CREATE TRIGGER {table}_search_au AFTER UPDATE ON {table} "
        f"BEGIN {deletes} {inserts} END"
    )


def _drop_triggers(table: str) -> None:
    for suffix in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_search_{suffix}")


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE search_word USING fts5("
        "title, body, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3')"
    )
    op.execute("CREATE VIRTUAL TABLE search_sub USING fts5(title, body, tokenize = 'trigram')")
    op.execute("CREATE VIRTUAL TABLE search_vocab USING fts5vocab(search_word, row)")
    for table, (kind, title, body) in SOURCES.items():
        for index in INDEXES:
            op.execute(
                f"INSERT INTO {index}(rowid, title, body) SELECT id * 8 + {kind}, "
                f"pw_norm({title.format(r=table)}), pw_norm({body.format(r=table)}) FROM {table}"
            )
        _create_triggers(table)


def downgrade() -> None:
    for table in SOURCES:
        _drop_triggers(table)
    op.execute("DROP TABLE search_vocab")
    op.execute("DROP TABLE search_sub")
    op.execute("DROP TABLE search_word")
