"""Smart-link ranking: shared-tag count first, then recency, then id."""

from datetime import UTC, datetime, timedelta

from podcast_workspace.domain.smart_links import LinkCandidate, LinkKind, rank_smart_links

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def cand(kind: LinkKind, item_id: int, tags: set[int], age_days: int = 0) -> LinkCandidate:
    return LinkCandidate(kind, item_id, frozenset(tags), T0 - timedelta(days=age_days))


def order(links: list) -> list[tuple[str, int]]:
    return [(link.kind.value, link.item_id) for link in links]


def test_ranked_by_number_of_shared_tags() -> None:
    links = rank_smart_links(
        {1, 2, 3},
        [
            cand(LinkKind.VOICE, 10, {1}),
            cand(LinkKind.IDEA, 20, {1, 2, 3}),
            cand(LinkKind.VOICE, 11, {2, 3, 99}),
        ],
    )
    assert order(links) == [("idea", 20), ("voice", 11), ("voice", 10)]
    assert [link.score for link in links] == [3, 2, 1]


def test_only_shared_tags_count() -> None:
    [link] = rank_smart_links({1, 2}, [cand(LinkKind.IDEA, 1, {2, 7, 8, 9})])
    assert link.shared_tag_ids == {2}
    assert link.score == 1


def test_items_without_shared_tags_are_excluded() -> None:
    links = rank_smart_links(
        {1},
        [cand(LinkKind.VOICE, 1, {2}), cand(LinkKind.IDEA, 2, set()), cand(LinkKind.IDEA, 3, {1})],
    )
    assert order(links) == [("idea", 3)]


def test_episode_without_tags_has_no_links() -> None:
    assert rank_smart_links(set(), [cand(LinkKind.VOICE, 1, {1})]) == []


def test_ties_prefer_recent_then_lower_id() -> None:
    links = rank_smart_links(
        {1, 2},
        [
            cand(LinkKind.VOICE, 5, {1}, age_days=30),
            cand(LinkKind.IDEA, 4, {2}, age_days=1),
            cand(LinkKind.VOICE, 3, {1}, age_days=1),
            cand(LinkKind.IDEA, 9, {1, 2}, age_days=400),
        ],
    )
    # the two-tag match wins despite its age; same-day ties fall back to id
    assert order(links) == [("idea", 9), ("voice", 3), ("idea", 4), ("voice", 5)]


def test_voices_and_ideas_rank_in_one_list() -> None:
    links = rank_smart_links(
        {1, 2},
        [cand(LinkKind.IDEA, 1, {1}), cand(LinkKind.VOICE, 1, {1, 2})],
    )
    assert order(links) == [("voice", 1), ("idea", 1)]
