"""Timestamp-note activation window. Pure logic, no Qt.

A note at position P is active while playback is inside [P - LEAD_MS, P + TRAIL_MS]
(both ends inclusive). Several notes may be active at once.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

LEAD_MS = 5_000
"""A note lights up this long before its position."""
TRAIL_MS = 10_000
"""...and stays lit this long after it."""


def is_active(note_position_ms: int, playback_ms: int) -> bool:
    return note_position_ms - LEAD_MS <= playback_ms <= note_position_ms + TRAIL_MS


@dataclass(frozen=True)
class ActivationChange:
    active: frozenset[int]
    entered: frozenset[int]
    left: frozenset[int]


class ActivationTracker:
    """Keeps the active set for a sorted note list; O(log n) per position update.

    Active notes satisfy P - LEAD <= t <= P + TRAIL, i.e. t - TRAIL <= P <= t + LEAD,
    so the active set is one contiguous slice of the notes sorted by position.
    """

    def __init__(self, notes: Iterable[tuple[int, int]] = ()) -> None:
        self._positions: list[int] = []
        self._ids: list[int] = []
        self._active: frozenset[int] = frozenset()
        self.set_notes(notes)

    def set_notes(self, notes: Iterable[tuple[int, int]]) -> None:
        """`notes` are (note_id, position_ms) pairs, any order. Keeps the current active set
        until the next update() so callers see a proper entered/left diff."""
        ordered = sorted(notes, key=lambda pair: (pair[1], pair[0]))
        self._ids = [note_id for note_id, _ in ordered]
        self._positions = [position for _, position in ordered]

    @property
    def active(self) -> frozenset[int]:
        return self._active

    def active_at(self, playback_ms: int) -> frozenset[int]:
        lo = bisect_left(self._positions, playback_ms - TRAIL_MS)
        hi = bisect_right(self._positions, playback_ms + LEAD_MS)
        return frozenset(self._ids[lo:hi])

    def update(self, playback_ms: int) -> ActivationChange:
        now = self.active_at(playback_ms)
        before = self._active
        self._active = now
        return ActivationChange(now, now - before, before - now)

    def reset(self) -> ActivationChange:
        """Nothing is playing any more (stopped / voice closed): everything deactivates."""
        before = self._active
        self._active = frozenset()
        return ActivationChange(frozenset(), frozenset(), before)
