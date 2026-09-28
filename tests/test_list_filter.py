"""Page-level list filtering: what a filter box keeps, what it takes away."""

import pytest

from podcast_workspace.domain.list_filter import FacetFilter, ListFilter, parse_list_filter
from podcast_workspace.domain.text import flatten_for_filter


def keeps(query: str, title: str, *tags: str) -> bool:
    return parse_list_filter(query).matches(title, tags)


def test_empty_query_keeps_everything() -> None:
    assert parse_list_filter("").is_empty
    assert parse_list_filter("   ").is_empty
    assert keeps("", "هر چیزی")


def test_title_matches_on_a_substring() -> None:
    assert keeps("فلسف", "درباره فلسفه ذهن")
    assert keeps("ذهن", "درباره فلسفه ذهن")
    assert not keeps("موسیقی", "درباره فلسفه ذهن")


def test_tag_names_are_searched_too() -> None:
    assert keeps("موسیقی", "ضبط دوم", "موسیقی سنتی")
    assert not keeps("موسیقی", "ضبط دوم", "مصاحبه")


def test_terms_are_anded_across_title_and_tags() -> None:
    assert keeps("ضبط مصاحبه", "ضبط دوم", "مصاحبه")
    assert not keeps("ضبط مصاحبه", "ضبط دوم", "موسیقی")


def test_hash_restricts_a_term_to_tags() -> None:
    assert keeps("#مصاحبه", "ضبط دوم", "مصاحبه")
    # the word is in the title, but #-marked means "tagged with"
    assert not keeps("#مصاحبه", "مصاحبه با نویسنده", "موسیقی")


def test_lone_hash_is_someone_still_typing() -> None:
    assert parse_list_filter("#").is_empty
    assert keeps("#", "هر چیزی")


def test_normalization_decides_nothing() -> None:
    assert keeps("روانشناسی", "روان‌شناسی شناختی")  # ZWNJ
    assert keeps("یک", "يک خاطره")  # Arabic ي
    assert keeps("۱۲", "voice-12.mp3")  # Persian digits
    assert keeps("WAV", "clip.wav")  # case


def test_latin_file_names_filter_by_substring() -> None:
    assert keeps("rec", "recording-04.wav")
    assert keeps("04", "recording-04.wav")
    assert not keeps("05", "recording-04.wav")


@pytest.mark.parametrize("query", ["#موسیقی سنتی", "سنتی #موسیقی"])
def test_mixing_a_tag_term_with_a_free_term(query: str) -> None:
    assert keeps(query, "سنتی‌ها", "موسیقی")
    assert not keeps(query, "ضبط دوم", "موسیقی")


def test_explicit_filter_is_reusable_without_parsing() -> None:
    assert ListFilter(free_terms=("abc",)).matches("xabcx")


def test_quotes_keep_words_together() -> None:
    assert keeps('"پدر بزرگ"', "خاطرهٔ پدر بزرگ")
    assert keeps('"پدر بزرگ"', "پدر، بزرگ")  # punctuation is not a word
    assert not keeps('"پدر بزرگ"', "بزرگ شدن پدر")
    assert keeps("پدر بزرگ", "بزرگ شدن پدر")  # unquoted: each on its own


def test_an_unclosed_quote_still_filters() -> None:
    assert keeps('"پدر بز', "خاطرهٔ پدر بزرگ")


def test_content_is_read_only_when_handed_over() -> None:
    assert not keeps("کودکی", "ضبط دوم")
    assert parse_list_filter("کودکی").matches("ضبط دوم", (), "از کودکی گفت")


# FacetFilter: the Ideas page's pinned queries, tag chips and the content switch -----------


def facet(*queries: str, tags: frozenset[int] = frozenset(), content: bool = False):
    return FacetFilter(tuple(parse_list_filter(q) for q in queries), tags, content)


def test_empty_facets_keep_everything() -> None:
    assert facet().is_empty
    assert facet("", "  ").is_empty
    assert facet(content=True).is_empty
    assert facet().matches("هر چیزی")


def test_each_pinned_query_narrows_further() -> None:
    both = facet("پدر", "برادر")
    assert both.matches("پدر و برادر")
    assert not both.matches("پدر و مادر")
    assert facet("پدر").matches("پدر و مادر")


def test_a_query_also_reads_the_item_tags() -> None:
    # "شه" is nowhere in the title, only in the tag «شهر»: still a match
    assert facet("شه").matches("ضبط دوم", ("شهر",))


def test_every_tag_chip_is_required() -> None:
    chips = facet("شه", tags=frozenset({1, 2}))
    assert chips.matches("شهرداری", (), (1, 2))
    assert not chips.matches("شهربازی", (), (2,))  # no tag 1
    assert not chips.matches("کتاب", (), (1, 2))  # the word is missing
    assert facet(tags=frozenset({3})).matches("هر چیزی", (), (3, 9))


def test_content_switch_opens_the_body() -> None:
    body = flatten_for_filter("از کودکی و پدرش گفت")
    assert not facet("کودکی").matches("ضبط دوم", content=body)
    assert facet("کودکی", content=True).matches("ضبط دوم", content=body)


def test_untagged_keeps_only_items_without_a_tag() -> None:
    review = FacetFilter(untagged=True)
    assert not review.is_empty  # on its own it narrows the list
    assert review.matches("ایدهٔ تازه", (), ())
    assert not review.matches("ایدهٔ تازه", ("شهر",), (1,))


def test_untagged_still_ands_with_the_typed_phrases() -> None:
    review = FacetFilter((parse_list_filter("کتاب"),), untagged=True)
    assert review.matches("کتاب‌فروشی", (), ())
    assert not review.matches("رادیو", (), ())
