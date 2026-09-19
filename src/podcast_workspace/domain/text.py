"""Text normalization shared by tag matching and full-text search."""

import re
from functools import lru_cache

from podcast_workspace.domain.rules import normalize_persian

ZWNJ = "‌"
_DIACRITICS = re.compile("[ً-ٰٟـ]")  # harakat, superscript alef, tatweel
_BIDI_MARKS = re.compile("[‎‏‪-‮⁦-⁩]")
_SEPARATORS = re.compile(r"[\s‌_\-/\\.,،؛:;!?؟«»()\[\]{}\"']+")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _base(text: str) -> str:
    text = normalize_persian(text).translate(_DIGITS)
    text = _BIDI_MARKS.sub("", text)
    return _DIACRITICS.sub("", text).casefold()


def normalize_for_match(text: str) -> str:
    """Short-string form for tag matching: ZWNJ and punctuation become single spaces."""
    return " ".join(_SEPARATORS.split(_base(text))).strip()


def normalize_for_index(text: str | None) -> str:
    """Long-text form stored in the FTS index and applied to queries.

    ZWNJ is removed (joining the parts): "روان‌شناسی" and "روانشناسی" index the same.
    """
    if not text:
        return ""
    return _base(text).replace(ZWNJ, "")


def query_terms(query: str) -> list[str]:
    """Split a search query into normalized, de-duplicated terms, order preserved."""
    seen: dict[str, None] = {}
    for term in _SEPARATORS.split(normalize_for_index(query)):
        if term:
            seen.setdefault(term, None)
    return list(seen)


_normalize_char = lru_cache(maxsize=8192)(normalize_for_index)


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """normalize_for_index(text) plus, per output char, its index in the original text."""
    out: list[str] = []
    positions: list[int] = []
    for i, ch in enumerate(text):
        for n in _normalize_char(ch):
            out.append(n)
            positions.append(i)
    return "".join(out), positions


def find_spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """Non-overlapping (start, end) spans in the ORIGINAL text where any term occurs."""
    normalized, positions = _normalized_with_map(text)
    spans: list[tuple[int, int]] = []
    for term in sorted(set(terms), key=len, reverse=True):
        if not term:
            continue
        start = normalized.find(term)
        while start != -1:
            a, b = positions[start], positions[start + len(term) - 1] + 1
            if all(b <= s or a >= e for s, e in spans):
                spans.append((a, b))
            start = normalized.find(term, start + len(term))
    return sorted(spans)


def make_snippet(text: str, terms: list[str], width: int = 90) -> str:
    """A one-line window of `text` centred on the first term occurrence."""
    flat = " ".join(text.split())
    spans = find_spans(flat, terms)
    if not spans or len(flat) <= width:
        return flat if len(flat) <= width else flat[:width].rstrip() + "…"
    first = spans[0][0]
    start = max(0, first - width // 3)
    end = min(len(flat), start + width)
    start = max(0, end - width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return prefix + flat[start:end].strip() + suffix
