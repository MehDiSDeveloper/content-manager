"""Fuzzy tag suggestion behaviour: what must be found, what must not, and in which order."""

import pytest

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.tag_matching import (
    find_exact,
    match_score,
    near_duplicates,
    normalize_for_match,
    rank_tags,
)


def tags(*names: str) -> list[Tag]:
    return [Tag(name=name, id=i) for i, name in enumerate(names, start=1)]


def top(query: str, pool: list[Tag]) -> str | None:
    found = rank_tags(query, pool)
    return found[0].tag.name if found else None


LIBRARY = tags(
    "تاریخ ایران",
    "فلسفه",
    "فلسفه ذهن",
    "پادکست",
    "مصاحبه",
    "موسیقی سنتی",
    "technology review",
    "book club",
    "روان‌شناسی",
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("پادکست", "پادکست"),  # exact
        ("پاد", "پادکست"),  # prefix
        ("فلس", "فلسفه"),  # prefix; shorter name wins the tie
        ("ذهن", "فلسفه ذهن"),  # second word
        ("سنتی", "موسیقی سنتی"),  # second word
        ("ایران تاریخ", "تاریخ ایران"),  # token order
        ("review", "technology review"),  # second word, latin
        ("rev tech", "technology review"),  # prefixes of both words, reversed
        ("club book", "book club"),
        ("پادکشت", "پادکست"),  # typo
        ("مصاحبع", "مصاحبه"),  # typo on last letter
        ("technolgy", "technology review"),  # dropped letter
        ("روانشناسی", "روان‌شناسی"),  # missing ZWNJ
        ("روان شناسی", "روان‌شناسی"),  # space instead of ZWNJ
    ],
)
def test_finds_expected_tag_first(query: str, expected: str) -> None:
    assert top(query, LIBRARY) == expected


def test_third_word_matches() -> None:
    pool = tags("سفر به شمال ایران", "سفرنامه")
    assert top("ایران", pool) == "سفر به شمال ایران"
    assert top("شمال", pool) == "سفر به شمال ایران"


def test_arabic_letter_variants_match_persian() -> None:
    # Arabic yeh (ي) and kaf (ك) typed on an Arabic keyboard layout
    assert top("موسيقي", LIBRARY) == "موسیقی سنتی"
    assert top("پادكست", LIBRARY) == "پادکست"


def test_case_and_diacritics_ignored() -> None:
    assert normalize_for_match("Book  CLUB") == "book club"
    assert normalize_for_match("فَلسَفه") == "فلسفه"
    assert top("BOOK", LIBRARY) == "book club"


def test_unrelated_query_finds_nothing() -> None:
    assert rank_tags("ورزش", LIBRARY) == []
    assert rank_tags("xyz", LIBRARY) == []


@pytest.mark.parametrize(
    ("query", "wrong"),
    [
        ("روان", "تاریخ ایران"),  # partial_ratio 86, but three edits away
        ("music", "موسیقی سنتی"),
        ("کلاب", "book club"),
        ("فلسطین", "فلسفه"),  # shares a 3-letter prefix, different word
    ],
)
def test_loose_alignments_are_not_suggested(query: str, wrong: str) -> None:
    assert wrong not in {m.tag.name for m in rank_tags(query, LIBRARY)}


def test_digits_in_query_must_match() -> None:
    pool = tags(*(f"قسمت {n}" for n in range(1, 16)))
    names = {m.tag.name for m in rank_tags("قسمت 1", pool, limit=20)}
    assert names == {"قسمت 1", *(f"قسمت {n}" for n in range(10, 16))}
    assert top("قسمت ۱۲", pool) == "قسمت 12"  # Persian digits


def test_transposed_letters_count_as_one_typo() -> None:
    assert top("podcsat", tags("podcast", "post")) == "podcast"


def test_one_or_two_letters_only_match_substrings() -> None:
    names = {m.tag.name for m in rank_tags("فل", LIBRARY)}
    assert names == {"فلسفه", "فلسفه ذهن"}
    assert rank_tags("zq", LIBRARY) == []


def test_empty_query_returns_nothing() -> None:
    assert rank_tags("   ", LIBRARY) == []


def test_exact_match_is_flagged_and_ranked_first() -> None:
    found = rank_tags("فلسفه", LIBRARY)
    assert found[0].exact
    assert found[0].tag.name == "فلسفه"
    assert not found[1].exact


def test_exclude_ids_skips_already_attached_tags() -> None:
    found = rank_tags("فلسفه", LIBRARY, exclude_ids={2})
    assert [m.tag.name for m in found][:1] == ["فلسفه ذهن"]


def test_find_exact_is_normalization_aware() -> None:
    exact = find_exact("  روان شناسی ", LIBRARY)
    assert exact is not None
    assert exact.name == "روان‌شناسی"
    assert find_exact("روان", LIBRARY) is None


@pytest.mark.parametrize("name", ["پادکستها", "Technology Reviews", "فلسفه‌ی"])
def test_near_duplicates_detected(name: str) -> None:
    assert near_duplicates(name, LIBRARY)


@pytest.mark.parametrize("name", ["ورزش", "سینما", "history"])
def test_distinct_names_are_not_near_duplicates(name: str) -> None:
    assert near_duplicates(name, LIBRARY) == []


def test_score_is_symmetric_enough_and_bounded() -> None:
    score = match_score("پادکست", "پادکست")
    assert score == 100
    assert 0 <= match_score("a", "b") <= 100
