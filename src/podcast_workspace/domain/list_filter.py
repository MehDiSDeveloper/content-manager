"""Narrowing one page's own list by title and tag name.

The near counterpart of `domain/search.py`: global search reads everything written in the
workspace — note bodies, transcripts, timestamps — and answers on its own page. This reads
only what the list in front of the user already shows, its title and its tags, so a page's
filter box takes rows away and never brings unfamiliar ones in. A page may also hand over
an item's content (an idea's full text, a voice's transcript) for the user to opt into.

Rules, in the order they surprise people least:
- terms are ANDed, so every keystroke narrows and never widens;
- a bare term matches the title or any tag name (or the content, when asked for);
- `#name` matches tag names only — how to say "tagged with" when the same word also
  turns up in titles;
- `"two words"` matches those words together, in that order.
Matching is on the normalized form (`normalize_for_index`), so ZWNJ, Arabic ی/ک, harakat,
Persian digits, letter case and punctuation never decide whether a row is shown.
Substring, not prefix: mid-word is where Persian compounds put the word you remember.

`FacetFilter` is the Ideas page's search: pinned queries and the one being typed, ANDed
together, plus required tags — or, instead of tags, "no tags at all", the weekly review's
question. Pinning a query never changes what it matches — it only keeps it while the next
is typed.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from podcast_workspace.domain.text import flatten_for_filter, query_terms

TAG_MARKER = "#"
_QUOTED = re.compile(r'"([^"]*)"?')  # an unclosed quote is someone still typing


@dataclass(frozen=True)
class ListFilter:
    """A parsed filter box. `ListFilter()` is the empty one: it keeps every row."""

    free_terms: tuple[str, ...] = ()
    tag_terms: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.free_terms and not self.tag_terms

    def matches(self, title: str, tag_names: Iterable[str] = (), content: str = "") -> bool:
        """`content` must already be flattened (`flatten_for_filter`): it is long, and a
        page flattens it once per load rather than once per keystroke."""
        if self.is_empty:
            return True
        tags = [flatten_for_filter(name) for name in tag_names]
        if not all(any(term in tag for tag in tags) for term in self.tag_terms):
            return False
        haystack = flatten_for_filter(title)
        return all(
            term in haystack or any(term in tag for tag in tags) or (content and term in content)
            for term in self.free_terms
        )


def parse_list_filter(query: str) -> ListFilter:
    """Split a filter box into its terms. A lone `#` is someone mid-word, not a term."""
    free: list[str] = []
    tagged: list[str] = []
    for phrase in _QUOTED.findall(query):
        words = flatten_for_filter(phrase)
        if words:
            free.append(words)
    for term in query_terms(_QUOTED.sub(" ", query)):
        if term.startswith(TAG_MARKER):
            rest = term.lstrip(TAG_MARKER)
            if rest:
                tagged.append(rest)
        else:
            free.append(term)
    return ListFilter(tuple(dict.fromkeys(free)), tuple(dict.fromkeys(tagged)))


@dataclass(frozen=True)
class FacetFilter:
    """Several queries and several tags at once; an item must satisfy every one.

    `tag_ids` are the chosen tags, every one required; `untagged` asks for items with no
    tag at all (the two exclude each other, so asking for both matches nothing).
    `in_content` lets the queries read the item's content as well.
    """

    queries: tuple[ListFilter, ...] = ()
    tag_ids: frozenset[int] = frozenset()
    in_content: bool = False
    untagged: bool = False
    _active: tuple[ListFilter, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_active", tuple(q for q in self.queries if not q.is_empty))

    @property
    def is_empty(self) -> bool:
        return not self._active and not self.tag_ids and not self.untagged

    def matches(
        self,
        title: str,
        tag_names: Iterable[str] = (),
        tag_ids: Iterable[int] = (),
        content: str = "",
    ) -> bool:
        ids = set(tag_ids)
        if self.tag_ids and not self.tag_ids <= ids:
            return False
        if self.untagged and ids:
            return False
        names = tuple(tag_names)
        body = content if self.in_content else ""
        return all(q.matches(title, names, body) for q in self._active)
