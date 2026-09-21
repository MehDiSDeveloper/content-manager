"""Undo/redo: the stack of changes the user can take back.

A recorded change is not a snapshot of the database. It is the pair of calls that move
one piece of data back and forth, plus enough description for the UI to name it and to
show the item it touched. Each entry therefore costs the few fields it has to put back
(a tag set, a title, one note body) — kilobytes, not megabytes — and the stack is capped
by both entry count and remembered text so a long session cannot grow without bound.

Who records: the services, beside the operation they invert — the UI only calls
`undo()` / `redo()`. Work that arrives from outside the user's hands (the Bale bot)
runs inside `suspended()` so it never lands on the user's stack; suspension is
per-thread, so the UI keeps recording while the bot worker does not.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum

# Depth: enough to walk back through a work session, small enough to stay cheap.
MAX_ENTRIES = 60
# Rough budget for the text held by the whole history, in characters.
MAX_WEIGHT = 1_000_000
# Consecutive edits of the same field collapse into one step while the typing keeps
# flowing (gap) and until the step covers a minute of it (span).
COALESCE_GAP_S = 8.0
COALESCE_SPAN_S = 60.0


class ChangeKind(StrEnum):
    """What was done. The UI turns this, with the target, into a Persian phrase."""

    CREATE = "create"
    DELETE = "delete"
    EDIT = "edit"
    RENAME = "rename"
    STATUS = "status"
    SEASON = "season"
    TAGS_ADDED = "tags_added"
    TAGS_REMOVED = "tags_removed"
    LINKED = "linked"
    UNLINKED = "unlinked"
    RECOLOR = "recolor"
    MERGE = "merge"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    TRASH = "trash"


class TargetKind(StrEnum):
    """What it was done to; the UI opens the matching page."""

    EPISODE = "episode"
    SEASON = "season"
    VOICE = "voice"
    IDEA = "idea"
    TAG = "tag"
    EPISODE_NOTE = "episode_note"
    TIMESTAMP_NOTE = "timestamp_note"


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    item_id: int
    owner_id: int | None = None  # the episode of a note, the voice of a timestamp note


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    target: Target
    undo: Callable[[], None]
    redo: Callable[[], None]
    # What the UI's phrase quotes: tag names, an episode title, a status value — data,
    # never UI text. The UI joins and translates them.
    details: tuple[str, ...] = ()
    weight: int = 0  # estimated characters held by the entry
    merge_key: str | None = None  # equal keys collapse into one step while typing
    at: float = field(default_factory=time.monotonic)
    started_at: float = field(default_factory=time.monotonic)


class HistoryService:
    """The undo and redo stacks. Thread-safe; recording is per-thread suspendable."""

    def __init__(self) -> None:
        self._undo: list[Change] = []
        self._redo: list[Change] = []
        self._lock = threading.RLock()
        self._local = threading.local()

    # recording -------------------------------------------------------------------------
    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Nothing this thread does inside the block reaches the stack."""
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth = depth

    @property
    def recording(self) -> bool:
        return getattr(self._local, "depth", 0) == 0

    def record(
        self,
        kind: ChangeKind,
        target: Target,
        *,
        undo: Callable[[], None],
        redo: Callable[[], None],
        details: tuple[str, ...] = (),
        weight: int = 0,
        merge_key: str | None = None,
    ) -> None:
        if not self.recording:
            return
        change = Change(
            kind=kind,
            target=target,
            undo=undo,
            redo=redo,
            details=tuple(d[:80] for d in details),
            weight=weight,
            merge_key=merge_key,
        )
        with self._lock:
            self._redo.clear()
            top = self._undo[-1] if self._undo else None
            if top is not None and self._mergeable(top, change):
                # Keep the oldest "before" and the newest "after": one step for the run.
                self._undo[-1] = replace(
                    change,
                    undo=top.undo,
                    weight=max(top.weight, change.weight),
                    started_at=top.started_at,
                )
            else:
                self._undo.append(change)
            self._trim()

    @staticmethod
    def _mergeable(top: Change, change: Change) -> bool:
        return (
            change.merge_key is not None
            and top.merge_key == change.merge_key
            and change.at - top.at <= COALESCE_GAP_S
            and change.at - top.started_at <= COALESCE_SPAN_S
        )

    def _trim(self) -> None:
        weight = sum(c.weight for c in self._undo)
        while self._undo and (len(self._undo) > MAX_ENTRIES or weight > MAX_WEIGHT):
            weight -= self._undo.pop(0).weight

    # using it --------------------------------------------------------------------------
    def undo(self) -> Change | None:
        """Take the top change back. Returns it so the UI can say what happened.

        A change that no longer applies (its item is gone) raises, and is dropped rather
        than left at the top to fail again; the entries below it stay usable.
        """
        return self._apply(self._undo, self._redo, forward=False)

    def redo(self) -> Change | None:
        return self._apply(self._redo, self._undo, forward=True)

    def _apply(self, source: list[Change], sink: list[Change], forward: bool) -> Change | None:
        with self._lock:
            if not source:
                return None
            change = source.pop()
        with self.suspended():  # the inverse must not record itself
            (change.redo if forward else change.undo)()
        with self._lock:
            sink.append(change)
            del sink[:-MAX_ENTRIES]
        return change

    def peek_undo(self) -> Change | None:
        with self._lock:
            return self._undo[-1] if self._undo else None

    def peek_redo(self) -> Change | None:
        with self._lock:
            return self._redo[-1] if self._redo else None

    def can_undo(self) -> bool:
        return self.peek_undo() is not None

    def can_redo(self) -> bool:
        return self.peek_redo() is not None

    def clear(self) -> None:
        """After an import: every entry points at rows that no longer exist."""
        with self._lock:
            self._undo.clear()
            self._redo.clear()
