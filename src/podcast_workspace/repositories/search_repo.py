"""Raw FTS5 queries over the search index built by migration a7f3c2d91e10."""

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from podcast_workspace.domain.search import SearchKind, decode_rowid

# Each source as (id, t = title, b = body, o = owner id).
_SOURCE_SQL: dict[SearchKind, str] = {
    SearchKind.EPISODE: "SELECT id, title AS t, next_action AS b, NULL AS o FROM episodes",
    SearchKind.IDEA_NOTE: "SELECT id, '' AS t, text AS b, NULL AS o FROM idea_notes",
    SearchKind.EPISODE_NOTE: "SELECT id, title AS t, body AS b, episode_id AS o FROM episode_notes",
    SearchKind.TIMESTAMP_NOTE: "SELECT id, '' AS t, text AS b, voice_id AS o FROM timestamp_notes",
    SearchKind.TAG: "SELECT id, name AS t, '' AS b, NULL AS o FROM tags",
    SearchKind.VOICE: "SELECT id, file_path AS t, '' AS b, NULL AS o FROM voices",
    SearchKind.TRANSCRIPT: "SELECT id, '' AS t, text AS b, voice_id AS o FROM transcripts",
}

# Display text differs from indexed text: a transcript hit is titled by its voice's file.
_DISPLAY_SQL: dict[SearchKind, str] = {
    SearchKind.TRANSCRIPT: (
        "SELECT tr.id AS id, v.file_path AS t, tr.text AS b, tr.voice_id AS o "
        "FROM transcripts tr JOIN voices v ON v.id = tr.voice_id"
    ),
}

_TAG_LINKS: dict[SearchKind, tuple[str, str]] = {
    SearchKind.EPISODE: ("episode_tags", "episode_id"),
    SearchKind.IDEA_NOTE: ("idea_note_tags", "idea_note_id"),
    SearchKind.VOICE: ("voice_tags", "voice_id"),
}

Match = tuple[SearchKind, int, float]  # kind, source id, bm25 rank (lower is better)
SourceText = tuple[str, str, int | None]  # title, body, owner id


def fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _match(self, table: str, expression: str, limit: int) -> list[Match]:
        rows = self.session.execute(
            text(
                f"SELECT rowid, bm25({table}, 4.0, 1.0) AS rank FROM {table} "
                f"WHERE {table} MATCH :q ORDER BY rank LIMIT :limit"
            ),
            {"q": expression, "limit": limit},
        )
        return [(*decode_rowid(rowid), rank) for rowid, rank in rows]

    def word_matches(self, expression: str, limit: int = 200) -> list[Match]:
        """`expression` is an FTS5 query over the unicode61 (word) index."""
        return self._match("search_word", expression, limit)

    def substring_matches(self, expression: str, limit: int = 200) -> list[Match]:
        """`expression` is an FTS5 query over the trigram (substring) index."""
        return self._match("search_sub", expression, limit)

    def vocabulary(self) -> list[str]:
        return list(self.session.scalars(text("SELECT term FROM search_vocab")))

    def source_texts(
        self, keys: Iterable[tuple[SearchKind, int]]
    ) -> dict[tuple[SearchKind, int], SourceText]:
        by_kind: dict[SearchKind, set[int]] = defaultdict(set)
        for kind, source_id in keys:
            by_kind[kind].add(source_id)
        result: dict[tuple[SearchKind, int], SourceText] = {}
        for kind, ids in by_kind.items():
            placeholders = ", ".join(str(int(i)) for i in ids)
            sql = _DISPLAY_SQL.get(kind, _SOURCE_SQL[kind])
            rows = self.session.execute(
                text(f"SELECT id, t, b, o FROM ({sql}) WHERE id IN ({placeholders})")
            )
            for source_id, title, body, owner in rows:
                result[(kind, source_id)] = (title or "", body or "", owner)
        return result

    def items_tagged(self, tag_ids: Iterable[int]) -> list[tuple[SearchKind, int, int]]:
        """(kind, item id, tag id) for every episode/idea/voice carrying one of the tags."""
        ids = ", ".join(str(int(i)) for i in set(tag_ids))
        if not ids:
            return []
        found: list[tuple[SearchKind, int, int]] = []
        for kind, (table, column) in _TAG_LINKS.items():
            rows = self.session.execute(
                text(f"SELECT {column}, tag_id FROM {table} WHERE tag_id IN ({ids})")
            )
            found.extend((kind, item_id, tag_id) for item_id, tag_id in rows)
        return found

    def rebuild(self) -> None:
        """Drop and repopulate both indexes from the source tables."""
        for index in ("search_word", "search_sub"):
            self.session.execute(text(f"DELETE FROM {index}"))
            for kind, sql in _SOURCE_SQL.items():
                self.session.execute(
                    text(
                        f"INSERT INTO {index}(rowid, title, body) "
                        f"SELECT id * 8 + {int(kind)}, pw_norm(t), pw_norm(b) FROM ({sql})"
                    )
                )
