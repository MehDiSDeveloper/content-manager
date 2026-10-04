"""Where the user has been, and how each page looked when they left it.

The pages are long-lived widgets in a QStackedWidget, so coming back to one would show
whatever it was left holding — except that each page reloads itself on `showEvent`, which
resets the filter box, the scroll position and sometimes the selection. "Back" that lands
on the right page but the wrong row is barely back at all, so a page hands over an opaque
snapshot of itself on the way out and gets it handed back on the way in.

A page joins in by implementing `nav_state()` / `restore_nav_state()`; one with nothing
worth restoring implements neither and still takes part in the history. The snapshot is
the page's own business — this module never looks inside it.
"""

import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

HISTORY_LIMIT = 30


@runtime_checkable
class StatefulPage(Protocol):
    def nav_state(self) -> Any: ...

    def restore_nav_state(self, state: Any) -> None: ...


def capture_state(page: QWidget) -> Any:
    """The page's snapshot, or None when it keeps none. Never raises: a page that cannot
    describe itself must still be reachable by Back."""
    if not isinstance(page, StatefulPage):
        return None
    try:
        return page.nav_state()
    except Exception:
        log.warning("nav_state of %s failed", type(page).__name__, exc_info=True)
        return None


def page_title(page: QWidget) -> str:
    """The page's own name, for a Back control that says where it goes."""
    return str(getattr(page, "nav_title", "") or "")


@dataclass(frozen=True)
class NavEntry:
    """One page, as it stood when the user left it."""

    page: QWidget
    state: Any = None

    @property
    def title(self) -> str:
        return page_title(self.page)

    def restore(self) -> None:
        if self.state is None or not isinstance(self.page, StatefulPage):
            return
        # The rows the snapshot names may be gone by now; the page itself is still the
        # right place to land, so a failed restore must not swallow the navigation.
        with contextlib.suppress(Exception):
            self.page.restore_nav_state(self.state)


class NavigationHistory:
    """The trail behind the current page, newest last, capped so it cannot grow forever."""

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self._limit = limit
        self._entries: list[NavEntry] = []

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def push(self, page: QWidget) -> None:
        """Record `page` as it stands right now. Re-entering the page it is already on
        would only add a step that goes nowhere."""
        if self._entries and self._entries[-1].page is page:
            self._entries[-1] = NavEntry(page, capture_state(page))
            return
        self._entries.append(NavEntry(page, capture_state(page)))
        del self._entries[: -self._limit]

    def push_entry(self, entry: NavEntry) -> None:
        """Record a snapshot taken earlier — the page left behind when search took over."""
        if self._entries and self._entries[-1].page is entry.page:
            self._entries[-1] = entry
            return
        self._entries.append(entry)
        del self._entries[: -self._limit]

    def pop_before(self, current: QWidget) -> NavEntry | None:
        """The last entry that is not the page already in front, dropping what it passes:
        a page reached twice in a row must not take two presses of Back to leave."""
        while self._entries:
            entry = self._entries.pop()
            if entry.page is not current:
                return entry
        return None

    def peek_before(self, current: QWidget) -> NavEntry | None:
        """Where Back would go, without going there — for the control that names it."""
        for entry in reversed(self._entries):
            if entry.page is not current:
                return entry
        return None

    def clear(self) -> None:
        self._entries.clear()
