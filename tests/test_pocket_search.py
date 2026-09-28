"""The bot's search: what it finds, in which order, and which tags it offers next."""

from datetime import datetime, timedelta

from podcast_workspace.domain.pocket_search import Entry, find, narrowing_tags

T0 = datetime(2026, 9, 1)


def entry(key: str, title: str, content: str = "", tags: dict[int, str] | None = None, age=0):
    tags = tags or {}
    return Entry(
        key, title, content, frozenset(tags), tuple(tags.values()), T0 - timedelta(days=age)
    )


def keys(found) -> list[str]:
    return [f.entry.key for f in found]


def test_named_matches_come_before_content_matches_and_newest_first_within_each() -> None:
    entries = [
        entry("old title", "خواب عمیق", age=5),
        entry("content", "یادداشت", "دربارهٔ خواب دیدن", age=0),
        entry("new title", "خواب و حافظه", age=1),
        entry("unrelated", "ورزش", "دویدن"),
    ]
    found = find(entries, "خواب", frozenset())
    assert keys(found) == ["new title", "old title", "content"]
    assert [f.in_content for f in found] == [False, False, True]


def test_a_tag_name_counts_as_the_name() -> None:
    found = find([entry("a", "ضبط دوم", tags={1: "سلامت"})], "سلامت", frozenset())
    assert keys(found) == ["a"] and not found[0].in_content


def test_words_may_be_split_between_title_and_content() -> None:
    found = find([entry("a", "خواب", "و حافظه")], "خواب حافظه", frozenset())
    assert keys(found) == ["a"]


def test_chosen_tags_are_all_required_and_alone_list_everything_tagged() -> None:
    entries = [
        entry("both", "یک", tags={1: "x", 2: "y"}),
        entry("one", "دو", tags={1: "x"}),
        entry("none", "سه"),
    ]
    assert keys(find(entries, "", frozenset({1}))) == ["both", "one"]
    assert keys(find(entries, "", frozenset({1, 2}))) == ["both"]


def test_narrowing_tags_split_the_results_most_frequent_first() -> None:
    entries = [
        entry("a", "خواب", tags={1: "همه", 2: "بیشتر", 3: "کمتر"}),
        entry("b", "خواب", tags={1: "همه", 2: "بیشتر"}),
        entry("c", "خواب", tags={1: "همه"}),
    ]
    found = find(entries, "خواب", frozenset())
    # «همه» is on every result: it would narrow nothing
    assert narrowing_tags(found, frozenset(), 4) == [(2, 2), (3, 1)]
    assert narrowing_tags(found, frozenset({2}), 4) == [(3, 1)]
