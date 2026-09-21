from datetime import UTC, datetime, timedelta

from podcast_workspace.domain.backup_reminder import backup_reminder

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def test_fresh_install_is_not_reminded():
    assert backup_reminder(NOW, NOW, None, None, 7) is None


def test_never_backed_up_counts_from_first_run():
    first = NOW - timedelta(days=8)
    reminder = backup_reminder(NOW, first, None, None, 7)
    assert reminder is not None
    assert reminder.never_backed_up
    assert reminder.days_since == 8


def test_recent_backup_is_quiet():
    first = NOW - timedelta(days=100)
    assert backup_reminder(NOW, first, NOW - timedelta(days=6, hours=23), None, 7) is None


def test_week_old_backup_is_due():
    first = NOW - timedelta(days=100)
    reminder = backup_reminder(NOW, first, NOW - timedelta(days=7), None, 7)
    assert reminder is not None
    assert not reminder.never_backed_up
    assert reminder.days_since == 7


def test_snooze_silences_until_it_runs_out():
    first = NOW - timedelta(days=100)
    last = NOW - timedelta(days=30)
    assert backup_reminder(NOW, first, last, NOW + timedelta(hours=1), 7) is None
    assert backup_reminder(NOW, first, last, NOW - timedelta(seconds=1), 7) is not None


def test_zero_interval_turns_reminders_off():
    first = NOW - timedelta(days=100)
    assert backup_reminder(NOW, first, None, None, 0) is None
