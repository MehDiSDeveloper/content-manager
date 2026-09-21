"""Archive and trash: the two ways a voice or an idea leaves the everyday lists.

Archived is put away, not gone: the item keeps every link and tag and is one switch away
(`ArchiveScope`). The lists and the search show the active items unless the user asks
for more.

Trashed is on its way out: hidden from every list, link, suggestion and search — the
trash page is the only place it shows — with everything it carries kept intact for
`TRASH_DAYS`, so a restore brings it back exactly as it was. After that it is purged
for good, and the database drops its tags, notes, transcript and links with it.
"""

from datetime import datetime, timedelta
from enum import StrEnum

TRASH_DAYS = 30


class ArchiveScope(StrEnum):
    """The three-way switch over a list (or a search): active is the default."""

    ACTIVE = "active"
    ALL = "all"
    ARCHIVED = "archived"

    def shows(self, archived: bool) -> bool:
        if self is ArchiveScope.ALL:
            return True
        return archived is (self is ArchiveScope.ARCHIVED)


class TrashKind(StrEnum):
    VOICE = "voice"
    IDEA = "idea"


def purge_at(deleted_at: datetime) -> datetime:
    """When an item put in the trash at `deleted_at` is gone for good."""
    return deleted_at + timedelta(days=TRASH_DAYS)


def purge_due(deleted_at: datetime, now: datetime) -> bool:
    return now >= purge_at(deleted_at)


def purge_cutoff(now: datetime) -> datetime:
    """Items trashed at or before this moment are due."""
    return now - timedelta(days=TRASH_DAYS)


def days_left(deleted_at: datetime, now: datetime) -> int:
    """Whole days until the purge, rounded up: "1 day left" until the very last moment."""
    remaining = purge_at(deleted_at) - now
    if remaining <= timedelta(0):
        return 0
    return remaining.days + (1 if remaining % timedelta(days=1) else 0)
