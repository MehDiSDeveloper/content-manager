"""Small UI helpers: localized formatting, error dialogs, background tasks, app-wide events."""

import contextlib
import threading
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import QCalendar, QDateTime, QLocale, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from podcast_workspace.domain.entities import EpisodeStatus
from podcast_workspace.domain.errors import (
    DomainError,
    DuplicateTagError,
    NearDuplicateTagError,
    NotFoundError,
    TagLimitExceededError,
    ValidationError,
)
from podcast_workspace.services.history import Change, ChangeKind, TargetKind
from podcast_workspace.ui import strings

_FA_LOCALE = QLocale(QLocale.Language.Persian, QLocale.Country.Iran)
_EN_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
_JALALI = QCalendar(QCalendar.System.Jalali)
_GREGORIAN = QCalendar(QCalendar.System.Gregorian)
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def local_digits(value: object) -> str:
    """Numbers in the script of the UI language: Persian digits, or left as they are."""
    text = str(value)
    return text.translate(_FA_DIGITS) if strings.LANGUAGE == "fa" else text


def numbered(title: str, number: int | None) -> str:
    """A season's or an episode's title with its number in front, when it has one."""
    if number is None:
        return title
    return strings.NUMBERED.format(n=local_digits(number), title=title)


def direction_mark(text: str) -> str:
    """The mark that makes `text` keep its own direction: RLM when its first strong letter
    is Persian (or any RTL script), LRM when it is Latin, the UI's own when it has none.

    A Persian title in the English UI, or a Latin file name in the Persian one, would
    otherwise be laid out in the UI's direction and come out scrambled.
    """
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return "\u200f"
        if kind == "L":
            return "\u200e"
    return strings.DIRECTION_MARK


def format_datetime(value: datetime | None) -> str:
    """ "۲۹ شهریور ۱۴۰۵، ۱۴:۰۵" in Persian (Jalali calendar), "Sep 21, 2026, 14:05" in English."""
    if value is None:
        return "—"
    local = QDateTime.fromSecsSinceEpoch(int(value.timestamp()))  # local time zone
    clock = local.time().toString("HH:mm")
    if strings.LANGUAGE != "fa":
        month = _GREGORIAN.monthName(
            _EN_LOCALE, local.date().month(), local.date().year(), QLocale.FormatType.ShortFormat
        )
        return f"{month} {local.date().day()}, {local.date().year()}, {clock}"
    parts = _JALALI.partsFromDate(local.date())
    month = _JALALI.monthName(_FA_LOCALE, parts.month, parts.year)
    return local_digits(f"{parts.day} {month} {parts.year}، {clock}")


def format_duration(ms: int) -> str:
    if ms <= 0:
        return strings.VOICE_DURATION_UNKNOWN
    seconds = ms // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return local_digits(text)


def format_clock(ms: int) -> str:
    """Playback clock: m:ss, or h:mm:ss past an hour, in the UI language's digits."""
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return local_digits(f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}")


def describe_error(exc: BaseException) -> str:
    match exc:
        case TagLimitExceededError():
            return strings.ERR_TAG_LIMIT.format(limit=local_digits(exc.limit))
        case DuplicateTagError():
            return strings.ERR_DUPLICATE_TAG.format(name=exc.existing_name)
        case NearDuplicateTagError():
            return strings.ERR_NEAR_DUPLICATE.format(
                names=strings.LIST_SEPARATOR.join(exc.similar_names)
            )
        case ValidationError():
            return strings.ERR_VALIDATION
        case NotFoundError():
            return strings.ERR_NOT_FOUND
        case DomainError():
            return str(exc)
        case _:
            return strings.ERR_UNEXPECTED.format(error=exc)


def _quote(text: str) -> str:
    return strings.QUOTE.format(text=text) if text else ""


def describe_change(change: Change) -> str:
    """Name a recorded change in words: "Remove tag “sport” from voice".

    The history keeps the parts as data (tag names, a status value); the wording is
    assembled here, so nothing below the UI ever holds a sentence.
    """
    details = list(change.details)
    if change.kind is ChangeKind.STATUS and details:
        with contextlib.suppress(KeyError, ValueError):
            details[0] = strings.STATUS_LABELS[EpisodeStatus(details[0])]
    if change.kind is ChangeKind.SEASON and details and not details[0]:
        details[0] = strings.SEASON_NONE  # moved out of every season
    if change.kind in (
        ChangeKind.TAGS_ADDED,
        ChangeKind.TAGS_REMOVED,
        ChangeKind.LINKED,  # several ideas put into an episode at once
        ChangeKind.UNLINKED,
    ):
        first, second = strings.LIST_SEPARATOR.join(d for d in details if d), ""
    else:
        first = details[0] if details else ""
        second = details[1] if len(details) > 1 else ""
    if change.target.kind is TargetKind.ITEMS:
        target = strings.UNDO_ITEMS.format(n=local_digits(change.target.item_id))
    else:
        target = strings.UNDO_TARGETS.get(change.target.kind, "")
    phrase = strings.UNDO_ACTIONS.get(change.kind, "").format(
        target=target,
        quoted=_quote(first),
        other=_quote(second),
    )
    return " ".join(phrase.split()) or strings.UNDO_SOMETHING


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    QMessageBox.warning(parent, strings.ERROR_TITLE, describe_error(exc))


def confirm(parent: QWidget, text: str, action: str | None = None) -> bool:
    """Ask before doing `action` (by default: deleting). Cancel is the safe default."""
    box = QMessageBox(QMessageBox.Icon.Question, strings.CONFIRM_TITLE, text, parent=parent)
    ok = box.addButton(action or strings.DELETE, QMessageBox.ButtonRole.AcceptRole)
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


def run_detached(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_failed: Callable[[BaseException], None],
) -> None:
    """Like run_async, but on a daemon thread: for work that cannot be cancelled (a model
    download) and must not keep the app from exiting, as the thread pool would."""
    relay = _Relay()
    _live_relays.add(relay)

    def finish(callback: Callable[[Any], None], value: Any) -> None:
        _live_relays.discard(relay)
        callback(value)

    relay.done.connect(lambda value: finish(on_done, value))
    relay.failed.connect(lambda exc: finish(on_failed, exc))
    threading.Thread(target=_Task(fn, relay).run, daemon=True).start()
