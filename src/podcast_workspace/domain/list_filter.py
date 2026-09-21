"""Narrowing one page's own list by title and tag name.

The near counterpart of `domain/search.py`: global search reads everything written in the
workspace — note bodies, transcripts, timestamps — and answers on its own page. This reads
only what the list in front of the user already shows, its title and its tags, so a page's
filter box takes rows away and never brings unfamiliar ones in.

Rules, in the order they surprise people least:
- terms are ANDed, so every keystroke narrows and never widens;
- a bare term matches the title or any tag name;
- `#name` matches tag names only — how to say "tagged with" when the same word also
  turns up in titles.
Matching is on the normalized form (`normalize_for_index`), so ZWNJ, Arabic ی/ک, harakat,
Persian digits and letter case never decide whether a row is shown. Substring, not prefix:
mid-word is where Persian compounds put the word you remember.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from podcast_workspace.domain.text import normalize_for_index, query_terms

TAG_MARKER = "#"


@dataclass(frozen=True)
class ListFilter:
    """A parsed filter box. `ListFilter()` is the empty one: it keeps every row."""

    free_terms: tuple[str, ...] = ()
    tag_terms: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.free_terms and not self.tag_terms

    def matches(self, title: str, tag_names: Iterable[str] = ()) -> bool:
        if self.is_empty:
            return True
        tags = [normalize_for_index(name) for name in tag_names]
        if not all(any(term in tag for tag in tags) for term in self.tag_terms):
            return False
        haystack = normalize_for_index(title)
        return all(term in haystack or any(term in tag for tag in tags) for term in self.free_terms)


def parse_list_filter(query: str) -> ListFilter:
    """Split a filter box into its terms. A lone `#` is someone mid-word, not a term."""
    free: list[str] = []
    tagged: list[str] = []
    for term in query_terms(query):
        if term.startswith(TAG_MARKER):
            rest = term.lstrip(TAG_MARKER)
            if rest:
                tagged.append(rest)
        else:
            free.append(term)
    return ListFilter(tuple(free), tuple(tagged))
