"""Smart linking: raw material (Voices, IdeaNotes) that shares tags with an episode.

Ranking: more shared tags first; ties go to the more recent item, then the lower id
(stable, so the list does not shuffle between refreshes).
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LinkKind(StrEnum):
    VOICE = "voice"
    IDEA = "idea"


@dataclass(frozen=True)
class LinkCandidate:
    kind: LinkKind
    item_id: int
    tag_ids: frozenset[int]
    recency: datetime  # imported_at for voices, updated_at for ideas


@dataclass(frozen=True)
class SmartLink:
    kind: LinkKind
    item_id: int
    shared_tag_ids: frozenset[int]
    recency: datetime

    @property
    def score(self) -> int:
        return len(self.shared_tag_ids)


def rank_smart_links(
    episode_tag_ids: Collection[int], candidates: Iterable[LinkCandidate]
) -> list[SmartLink]:
    """Every candidate sharing at least one tag, best first."""
    wanted = frozenset(episode_tag_ids)
    if not wanted:
        return []
    links = [
        SmartLink(c.kind, c.item_id, c.tag_ids & wanted, c.recency)
        for c in candidates
        if c.tag_ids & wanted
    ]
    links.sort(key=lambda link: (-link.score, -link.recency.timestamp(), link.item_id))
    return links
