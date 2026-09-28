"""Finding one's own ideas from the phone: the Bale bot's search. Pure functions.

The matching is the Ideas page's (`domain/list_filter.py`): terms ANDed, substrings of the
normalized text, chosen tags all required. The content — an idea's whole text, a voice's
notes and transcript — is always read, since a phone has no «در محتوا» switch to flip.

Order, best first:
1. found by its title or a tag name (what you remember calling it)
2. found only in the content
and within each, the newest first.

Narrowing tags are the ones that would split the current results in two: on some of them
but not all, the most frequent first. A tag every result carries narrows nothing.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from podcast_workspace.domain.list_filter import FacetFilter, parse_list_filter
from podcast_workspace.domain.text import flatten_for_filter


@dataclass(frozen=True)
class Entry[K]:
    """One searchable item. `key` is the caller's own handle on it, passed through."""

    key: K
    title: str
    content: str
    tag_ids: frozenset[int]
    tag_names: tuple[str, ...]
    when: datetime


@dataclass(frozen=True)
class Found[K]:
    entry: Entry[K]
    in_content: bool  # found only in the content, so a snippet should show where


def find[K](entries: Iterable[Entry[K]], words: str, tag_ids: frozenset[int]) -> list[Found[K]]:
    """Every entry carrying all of `tag_ids` whose title, tags or content hold every word."""
    query = parse_list_filter(words)
    by_name = FacetFilter((query,), tag_ids)
    everywhere = FacetFilter((query,), tag_ids, in_content=True)
    found: list[Found[K]] = []
    for entry in entries:
        if by_name.matches(entry.title, entry.tag_names, entry.tag_ids):
            found.append(Found(entry, in_content=False))
        elif not query.is_empty and everywhere.matches(
            entry.title, entry.tag_names, entry.tag_ids, flatten_for_filter(entry.content)
        ):
            found.append(Found(entry, in_content=True))
    found.sort(key=lambda f: f.entry.when, reverse=True)
    found.sort(key=lambda f: f.in_content)  # stable: the newest first within each tier
    return found


def narrowing_tags[K](
    found: list[Found[K]], chosen: frozenset[int], limit: int
) -> list[tuple[int, int]]:
    """(tag id, how many results carry it) for the tags worth offering as a next step."""
    counts = Counter(t for f in found for t in f.entry.tag_ids if t not in chosen)
    useful = [(tag_id, n) for tag_id, n in counts.items() if n < len(found)]
    useful.sort(key=lambda tn: (-tn[1], tn[0]))
    return useful[:limit]
