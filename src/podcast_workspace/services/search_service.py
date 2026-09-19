"""Global search over episode titles, all note text, tag names and voice file names.

Three passes, merged and de-duplicated, best quality first:
1. word index (unicode61): every term as a word prefix        -> MatchQuality.WORD
2. trigram index: every term as a substring (terms >= 3 chars) -> MatchQuality.SUBSTRING
3. items carrying a tag found in 1/2                           -> MatchQuality.TAGGED
4. only if little was found: misspelled terms are corrected against the index
   vocabulary (fts5vocab) and the word query is re-run         -> MatchQuality.TYPO
"""

import bisect
from pathlib import PureWindowsPath

from rapidfuzz import process
from rapidfuzz.distance import OSA
from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.search import (
    MatchQuality,
    SearchHit,
    SearchKind,
    SearchResult,
)
from podcast_workspace.domain.text import make_snippet, query_terms
from podcast_workspace.repositories.db import WriteCounter
from podcast_workspace.repositories.search_repo import Match, fts_phrase
from podcast_workspace.repositories.unit_of_work import UnitOfWork

MAX_HITS = 60
TYPO_PASS_BELOW = 5  # run the typo pass when fewer hits than this
MIN_TYPO_TERM = 4
MIN_SUBSTRING_TERM = 3  # trigram tokenizer cannot match shorter strings

Key = tuple[SearchKind, int]


def _typo_budget(term: str) -> int:
    return 1 if len(term) <= 6 else 2


def _is_known(sorted_vocab: list[str], term: str) -> bool:
    """The term already occurs in the index as a word prefix or inside a word."""
    i = bisect.bisect_left(sorted_vocab, term)
    if i < len(sorted_vocab) and sorted_vocab[i].startswith(term):
        return True
    return any(term in word for word in sorted_vocab)


def corrections_for(term: str, vocab: list[str], limit: int = 3) -> list[str]:
    """Vocabulary words (or word starts) within the typo budget of `term`."""
    budget = _typo_budget(term)
    found: dict[str, int] = {}
    for choice, dist, _ in process.extract(
        term, vocab, scorer=OSA.distance, score_cutoff=budget, limit=limit
    ):
        found[choice] = int(dist)
    heads = [v[: len(term)] for v in vocab]
    for _, dist, index in process.extract(
        term, heads, scorer=OSA.distance, score_cutoff=budget, limit=limit * 4
    ):
        word = vocab[index]
        if len(word) >= len(term):
            found.setdefault(word, int(dist))
    ranked = sorted(found.items(), key=lambda kv: (kv[1], len(kv[0])))
    return [word for word, _ in ranked if word != term][:limit]


class SearchService:
    def __init__(self, session_factory: sessionmaker[Session], writes: WriteCounter) -> None:
        self._sf = session_factory
        self._writes = writes
        self._vocab: list[str] = []
        self._vocab_version = -1

    def _vocabulary(self, uow: UnitOfWork) -> list[str]:
        if self._vocab_version != self._writes.value:
            version = self._writes.value
            self._vocab = uow.search.vocabulary()  # fts5vocab returns terms sorted
            self._vocab_version = version
        return self._vocab

    def warm_up(self) -> None:
        """Load the typo-correction vocabulary ahead of the first search (safe off-thread)."""
        with UnitOfWork(self._sf) as uow:
            self._vocabulary(uow)

    def search(self, query: str, limit: int = MAX_HITS) -> SearchResult:
        terms = query_terms(query)
        if not terms:
            return SearchResult(query, [], {})
        best: dict[Key, tuple[MatchQuality, float, str | None]] = {}

        def add(matches: list[Match], quality: MatchQuality) -> None:
            for kind, source_id, rank in matches:
                key = (kind, source_id)
                if key not in best or (quality, rank) < best[key][:2]:
                    best[key] = (quality, rank, None)

        corrections: dict[str, str] = {}
        with UnitOfWork(self._sf) as uow:
            repo = uow.search
            add(
                repo.word_matches(" AND ".join(f"{fts_phrase(t)}*" for t in terms)),
                MatchQuality.WORD,
            )
            if all(len(t) >= MIN_SUBSTRING_TERM for t in terms):
                add(
                    repo.substring_matches(" AND ".join(fts_phrase(t) for t in terms)),
                    MatchQuality.SUBSTRING,
                )

            if len(best) < TYPO_PASS_BELOW:
                vocab = self._vocabulary(uow)
                groups: list[str] = []
                for term in terms:
                    alternatives = [term]
                    if len(term) >= MIN_TYPO_TERM and not _is_known(vocab, term):
                        fixes = corrections_for(term, vocab)
                        if fixes:
                            corrections[term] = fixes[0]
                        alternatives += fixes
                    groups.append(
                        "(" + " OR ".join(f"{fts_phrase(a)}*" for a in alternatives) + ")"
                    )
                if corrections:
                    add(repo.word_matches(" AND ".join(groups)), MatchQuality.TYPO)

            tag_names: dict[int, str] = {}
            tag_keys = [key for key in best if key[0] is SearchKind.TAG]
            if tag_keys:
                texts = repo.source_texts(tag_keys)
                tag_names = {key[1]: texts[key][0] for key in tag_keys if key in texts}
                for kind, item_id, tag_id in repo.items_tagged(tag_names):
                    key = (kind, item_id)
                    tag_rank = best[(SearchKind.TAG, tag_id)][1]
                    if key not in best or best[key][0] > MatchQuality.TAGGED:
                        best[key] = (MatchQuality.TAGGED, tag_rank, tag_names[tag_id])

            ordered = sorted(best.items(), key=lambda kv: (kv[1][0], kv[1][1]))[:limit]
            texts = repo.source_texts(key for key, _ in ordered)

        highlight = terms + list(corrections.values())
        hits: list[SearchHit] = []
        for (kind, source_id), (quality, rank, via_tag) in ordered:
            if (kind, source_id) not in texts:
                continue
            title, body, owner = texts[(kind, source_id)]
            if kind is SearchKind.VOICE:
                title = PureWindowsPath(title).name
            elif not title.strip() and body.strip():  # ideas/notes: first line as title
                first = body.strip().splitlines()[0]
                title = first if len(first) <= 70 else first[:70].rstrip() + "…"
            hits.append(
                SearchHit(
                    kind=kind,
                    source_id=source_id,
                    title=title,
                    snippet=make_snippet(body, highlight) if body else "",
                    quality=quality,
                    rank=rank,
                    owner_id=owner,
                    via_tag=via_tag,
                )
            )
        return SearchResult(query, hits, corrections)

    def rebuild_index(self) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.search.rebuild()
        self._writes.bump()
