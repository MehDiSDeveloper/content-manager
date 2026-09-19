"""Pure business rules. No I/O, no framework imports."""

import re
from collections.abc import Callable, Collection

from podcast_workspace.domain.errors import (
    InvalidTagHierarchyError,
    TagLimitExceededError,
    ValidationError,
)

MAX_TAGS_PER_ITEM = 15
"""Hard cap on tags attached to a single Voice or IdeaNote."""

MAX_TAG_NAME_LENGTH = 64

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Arabic code points that look identical to Persian ones but break equality/search.
_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})


def normalize_persian(text: str) -> str:
    """Map Arabic yeh/kaf/alef-maksura to their Persian forms."""
    return text.translate(_ARABIC_TO_PERSIAN)


def ensure_tag_limit(tag_ids: Collection[int], limit: int = MAX_TAGS_PER_ITEM) -> None:
    """Raise if a tag set (after de-duplication) is larger than the limit."""
    count = len(set(tag_ids))
    if count > limit:
        raise TagLimitExceededError(limit, count)


def normalize_tag_name(name: str) -> str:
    cleaned = " ".join(normalize_persian(name).split())
    if not cleaned:
        raise ValidationError("Tag name must not be empty.")
    if len(cleaned) > MAX_TAG_NAME_LENGTH:
        raise ValidationError(f"Tag name must be at most {MAX_TAG_NAME_LENGTH} characters.")
    return cleaned


def normalize_color(color: str) -> str:
    if not _HEX_COLOR.match(color):
        raise ValidationError(f"Tag color must look like #RRGGBB, got {color!r}.")
    return color.lower()


def ensure_valid_parent(
    tag_id: int | None,
    new_parent_id: int | None,
    parent_of: Callable[[int], int | None],
) -> None:
    """Reject a parent assignment that would create a cycle.

    `parent_of` returns the current parent id of a tag (None for a root tag).
    """
    if new_parent_id is None or tag_id is None:
        return
    seen: set[int] = set()
    cursor: int | None = new_parent_id
    while cursor is not None:
        if cursor == tag_id:
            raise InvalidTagHierarchyError("A tag cannot be nested inside itself.")
        if cursor in seen:  # pre-existing corruption; stop instead of looping forever
            break
        seen.add(cursor)
        cursor = parent_of(cursor)


def ensure_non_empty(value: str, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError(f"{field} must not be empty.")
    return stripped


def ensure_non_negative(value: int, field: str) -> int:
    if value < 0:
        raise ValidationError(f"{field} must be >= 0.")
    return value
