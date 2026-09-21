"""Page-level list filtering: what a filter box keeps, what it takes away."""

import pytest

from podcast_workspace.domain.list_filter import ListFilter, parse_list_filter


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
