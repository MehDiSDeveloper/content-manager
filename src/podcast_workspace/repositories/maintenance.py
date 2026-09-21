"""Whole-database operations used by backup/restore: snapshots and wiping user data."""

import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

# Child tables first so foreign keys never block a delete. `settings` is not user content.
USER_TABLES = (
    "episode_tags",
    "voice_tags",
    "idea_note_tags",
    "episode_voices",
    "episode_idea_notes",
    "transcripts",
    "timestamp_notes",
    "episode_notes",
    "episodes",
    "seasons",
    "idea_notes",
    "voices",
    "tags",
)


class MaintenanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot_to(self, target: Path) -> None:
        """Consistent copy of the whole database file (SQLite online backup)."""
        source = self.session.connection().connection.dbapi_connection
        assert isinstance(source, sqlite3.Connection)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as destination:
            source.backup(destination)
        destination.close()

    def wipe_user_data(self) -> None:
        """Delete every episode, voice, idea, note, transcript and tag. Triggers keep the
        search index in step. Runs inside the caller's transaction."""
        for table in USER_TABLES:
            self.session.execute(text(f"DELETE FROM {table}"))
        self.session.expire_all()
