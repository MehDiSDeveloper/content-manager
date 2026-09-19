"""Forgiving tag-name matching, used to suggest existing tags while the user types.

Score = max(token_set_ratio, partial_ratio, word_prefix_score), all 0..100.
- token_set_ratio: word-order independent, subset of words scores 100
- partial_ratio: substring / typo tolerant alignment
- word_prefix_score: every query word is a prefix of (or a near-typo of the start of)
  some candidate word — this is what makes "rev tech" find "technology review".
Non-substring matches are gated by a per-word typo budget (OSA edits: 1 up to 6 letters,
2 beyond); if some query word fails it, token_set_ratio scaled by the matched-word
fraction is used instead. Queries shorter than MIN_FUZZY_LENGTH
match by substring only; fuzzy scores on one or two letters are noise.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import OSA

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.text import normalize_for_match

MATCH_THRESHOLD = 68.0
NEAR_DUPLICATE_THRESHOLD = 88.0
MIN_FUZZY_LENGTH = 3


def _allowed_typos(word: str) -> int:
    if len(word) <= MIN_FUZZY_LENGTH:
        return 0
    return 1 if len(word) <= 6 else 2


def _word_matches(qw: str, candidate_words: list[str]) -> bool:
    """Query word is a prefix of a candidate word, extends one, or is a small typo away."""
    budget = _allowed_typos(qw)
    for cw in candidate_words:
        if cw.startswith(qw) or (len(cw) >= MIN_FUZZY_LENGTH and qw.startswith(cw)):
            return True
        if budget and (
            OSA.distance(qw, cw, score_cutoff=budget) <= budget
            or OSA.distance(qw, cw[: len(qw)], score_cutoff=budget) <= budget
        ):
            return True
    return False


def _word_prefix_score(query_words: list[str], candidate_words: list[str]) -> float:
    """Mean per-word similarity, where a prefix hit counts as a perfect word match."""
    total = 0.0
    for qw in query_words:
        best = 0.0
        for cw in candidate_words:
            if cw.startswith(qw):
                best = 100.0
                break
            best = max(best, fuzz.ratio(qw, cw[: len(qw)]), fuzz.ratio(qw, cw))
        total += best
    return total / len(query_words)


def match_score(query: str, candidate: str) -> float:
    """0..100 similarity of a typed query to a tag name. Both are normalized here."""
    q = normalize_for_match(query)
    c = normalize_for_match(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    q_compact, c_compact = q.replace(" ", ""), c.replace(" ", "")
    if len(q_compact) < MIN_FUZZY_LENGTH:
        return 90.0 if q in c else 0.0
    if q_compact in c_compact:  # substring, even across a missing space/ZWNJ
        return max(fuzz.partial_ratio(q, c), fuzz.partial_ratio(q_compact, c_compact))

    q_words, c_words = q.split(), c.split()
    fuzzy = max(
        fuzz.token_set_ratio(q, c),
        fuzz.partial_ratio(q, c),
        _word_prefix_score(q_words, c_words),
    )
    # partial_ratio aligns loosely: "روان" vs "ایران" scores 86 with three edits.
    # Trust the fuzzy score only if every meaningful query word is a prefix or a real typo.
    # Single letters are skipped (e.g. the "ی" of "فلسفه‌ی"), single digits are not.
    meaningful = [w for w in q_words if len(w) > 1 or w.isdigit()] or q_words
    matched = sum(_word_matches(w, c_words) for w in meaningful)
    if matched == len(meaningful):
        return fuzzy
    # Some typed word matches nothing: keep only word-set overlap, scaled by how much matched.
    return fuzz.token_set_ratio(q, c) * matched / len(meaningful)


@dataclass(frozen=True)
class TagMatch:
    tag: Tag
    score: float
    exact: bool


def _tier(q: str, c: str) -> int:
    """Tie-breaker: lower is better."""
    if q == c:
        return 0
    if c.startswith(q):
        return 1
    if any(word.startswith(q) for word in c.split()):
        return 2
    if q in c:
        return 3
    return 4


def rank_tags(
    query: str,
    tags: Iterable[Tag],
    limit: int = 8,
    threshold: float = MATCH_THRESHOLD,
    exclude_ids: set[int] | None = None,
) -> list[TagMatch]:
    q = normalize_for_match(query)
    if not q:
        return []
    excluded = exclude_ids or set()
    scored: list[tuple[float, int, int, TagMatch]] = []
    for tag in tags:
        if tag.id in excluded:
            continue
        c = normalize_for_match(tag.name)
        score = match_score(q, c)
        if score < threshold:
            continue
        match = TagMatch(tag=tag, score=score, exact=_compact(q) == _compact(c))
        scored.append((-score, _tier(q, c), len(c), match))
    scored.sort(key=lambda item: item[:3])
    return [item[3] for item in scored[:limit]]


def _compact(normalized: str) -> str:
    return normalized.replace(" ", "")


def find_exact(query: str, tags: Iterable[Tag]) -> Tag | None:
    """Tag whose name equals `query` ignoring case, spacing, ZWNJ and Arabic letter forms."""
    q = _compact(normalize_for_match(query))
    if not q:
        return None
    return next((t for t in tags if _compact(normalize_for_match(t.name)) == q), None)


def near_duplicates(name: str, tags: Iterable[Tag]) -> list[TagMatch]:
    """Existing tags so similar to `name` that creating it would be a near-duplicate."""
    return rank_tags(name, tags, limit=5, threshold=NEAR_DUPLICATE_THRESHOLD)
