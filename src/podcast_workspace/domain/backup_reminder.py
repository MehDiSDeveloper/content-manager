"""When to remind the user to take a backup. Pure: the caller supplies every date.

The reminder counts from the last export. Someone who has never exported counts from the
day they started using the app, so a first launch is never greeted by a nag about data
that does not exist yet. A snooze ("remind me tomorrow") silences it until it runs out.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class BackupReminder:
    """A reminder that is due: how long since the last backup, and whether there was one."""

    days_since: int
    never_backed_up: bool


def backup_reminder(
    now: datetime,
    first_run_at: datetime,
    last_backup_at: datetime | None,
    snoozed_until: datetime | None,
    interval_days: int,
) -> BackupReminder | None:
    """The reminder to show now, or None. `interval_days` <= 0 turns reminders off."""
    if interval_days <= 0:
        return None
    if snoozed_until is not None and now < snoozed_until:
        return None
    since = last_backup_at or first_run_at
    elapsed = now - since
    if elapsed < timedelta(days=interval_days):
        return None
    return BackupReminder(days_since=elapsed.days, never_backed_up=last_backup_at is None)
