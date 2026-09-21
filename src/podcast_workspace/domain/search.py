"""Search result model and the rowid scheme shared by the FTS index and its triggers.

Every indexed row gets FTS rowid = source_id * 8 + kind. The triggers in migration
`a7f3c2d91e10` hard-code these numbers; change both together or not at all.
"""

from dataclasses import dataclass
from enum import IntEnum


class SearchKind(IntEnum):
    EPISODE = 1
    IDEA_NOTE = 2
    EPISODE_NOTE = 3
    TIMESTAMP_NOTE = 4
    TAG = 5
    VOICE = 6
    TRANSCRIPT = 7


ROWID_STRIDE = 8


def encode_rowid(kind: SearchKind, source_id: int) -> int:
    return source_id * ROWID_STRIDE + kind


def decode_rowid(rowid: int) -> tuple[SearchKind, int]:
    return SearchKind(rowid % ROWID_STRIDE), rowid // ROWID_STRIDE


class MatchQuality(IntEnum):
    """How a hit was found; lower is better and sorts first."""

    WORD = 0  # every term is a word or word prefix
    SUBSTRING = 1  # every term occurs inside a word
    TAGGED = 2  # the item carries a tag that matched
    TYPO = 3  # found after correcting misspelled terms


@dataclass(frozen=True)
class SearchHit:
    kind: SearchKind
    source_id: int
    title: str
    snippet: str
    quality: MatchQuality
    rank: float  # bm25 within a quality tier; lower is better
    owner_id: int | None = None  # episode of an EpisodeNote; voice of a TimestampNote/Transcript
    via_tag: str | None = None  # tag name, for MatchQuality.TAGGED


@dataclass(frozen=True)
class SearchResult:
    query: str
    hits: list[SearchHit]
    corrections: dict[str, str]  # misspelled term -> vocabulary term used instead
    more_in_content: int = 0  # hits a titles-only search left for the content to find
