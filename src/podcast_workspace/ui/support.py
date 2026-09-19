"""Small UI helpers: Persian formatting, error dialogs, background tasks, app-wide events."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import QCalendar, QDateTime, QLocale, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from podcast_workspace.domain.errors import (
    DomainError,
    DuplicateTagError,
    InvalidTagHierarchyError,
    NearDuplicateTagError,
    NotFoundError,
    TagLimitExceededError,
    ValidationError,
)
from podcast_workspace.ui import strings

_LOCALE = QLocale(QLocale.Language.Persian, QLocale.Country.Iran)
_JALALI = QCalendar(QCalendar.System.Jalali)
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = QDateTime.fromSecsSinceEpoch(int(value.timestamp()))  # local time zone
    parts = _JALALI.partsFromDate(local.date())
    month = _JALALI.monthName(_LOCALE, parts.month, parts.year)
    return fa_digits(f"{parts.day} {month} {parts.year}، {local.time().toString('HH:mm')}")


def format_duration(ms: int) -> str:
    if ms <= 0:
        return strings.VOICE_DURATION_UNKNOWN
    seconds = ms // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return fa_digits(text)


def format_clock(ms: int) -> str:
    """Playback clock: m:ss, or h:mm:ss past an hour. Persian digits."""
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return fa_digits(f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}")


def describe_error(exc: BaseException) -> str:
    match exc:
        case TagLimitExceededError():
            return strings.ERR_TAG_LIMIT.format(limit=fa_digits(exc.limit))
        case DuplicateTagError():
            return strings.ERR_DUPLICATE_TAG.format(name=exc.existing_name)
        case NearDuplicateTagError():
            return strings.ERR_NEAR_DUPLICATE.format(names="، ".join(exc.similar_names))
        case InvalidTagHierarchyError():
            return strings.ERR_HIERARCHY
        case ValidationError():
            return strings.ERR_VALIDATION
        case NotFoundError():
            return strings.ERR_NOT_FOUND
        case DomainError():
            return str(exc)
        case _:
            return strings.ERR_UNEXPECTED.format(error=exc)


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    QMessageBox.warning(parent, strings.ERROR_TITLE, describe_error(exc))


def confirm(parent: QWidget, text: str, action: str = strings.DELETE) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, strings.CONFIRM_TITLE, text, parent=parent)
    ok = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(strings.CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ok


class AppEvents(QObject):
    """App-wide notifications so pages stay consistent without knowing each other."""

    tags_changed = Signal()
    data_changed = Signal()


class _Relay(QObject):
    """Lives in the GUI thread so worker results are delivered there (queued)."""

    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], relay: _Relay) -> None:
        super().__init__()
        self._fn = fn
        self._relay = relay

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # delivered to the GUI thread, never swallowed
            self._relay.failed.emit(exc)
        else:
            self._relay.done.emit(result)


_live_relays: set[_Relay] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_failed: Callable[[BaseException], None],
) -> None:
    """Run `fn` on the global thread pool; callbacks run on the GUI thread."""
    relay = _Relay()
    _live_relays.add(relay)

    def finish(callback: Callable[[Any], None], value: Any) -> None:
        _live_relays.discard(relay)
        callback(value)

    relay.done.connect(lambda value: finish(on_done, value))
    relay.failed.connect(lambda exc: finish(on_failed, exc))
    QThreadPool.globalInstance().start(_Task(fn, relay))
