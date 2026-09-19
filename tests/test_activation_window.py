"""Timestamp-note activation window: [position - 5s, position + 10s], inclusive."""

import pytest

from podcast_workspace.domain.activation import (
    LEAD_MS,
    TRAIL_MS,
    ActivationTracker,
    is_active,
)


@pytest.mark.parametrize(
    ("playback", "expected"),
    [
        (60_000 - LEAD_MS - 1, False),
        (60_000 - LEAD_MS, True),
        (60_000, True),
        (60_000 + TRAIL_MS, True),
        (60_000 + TRAIL_MS + 1, False),
    ],
)
def test_window_boundaries(playback: int, expected: bool) -> None:
    assert is_active(60_000, playback) is expected
    assert (1 in ActivationTracker([(1, 60_000)]).active_at(playback)) is expected


def test_window_is_asymmetric() -> None:
    assert LEAD_MS == 5_000
    assert TRAIL_MS == 10_000
    assert not is_active(20_000, 14_000)  # 6 s before: too early
    assert is_active(20_000, 29_000)  # 9 s after: still active


def test_note_at_zero_is_active_from_the_start() -> None:
    assert ActivationTracker([(7, 0)]).active_at(0) == {7}


def test_several_notes_active_at_once() -> None:
    tracker = ActivationTracker([(1, 10_000), (2, 14_000), (3, 18_000), (4, 40_000)])
    assert tracker.active_at(15_000) == {1, 2, 3}
    assert tracker.active_at(21_000) == {2, 3}
    assert tracker.active_at(36_000) == {4}
    assert tracker.active_at(30_000) == frozenset()


def test_same_position_notes_activate_together() -> None:
    tracker = ActivationTracker([(1, 5_000), (2, 5_000)])
    assert tracker.active_at(0) == {1, 2}


def test_unsorted_input_matches_brute_force() -> None:
    notes = [(i, (i * 7919) % 120_000) for i in range(200)]
    tracker = ActivationTracker(notes)
    for t in range(0, 130_000, 250):
        expected = {note_id for note_id, pos in notes if is_active(pos, t)}
        assert tracker.active_at(t) == expected


def test_update_reports_enter_and_leave() -> None:
    tracker = ActivationTracker([(1, 10_000), (2, 30_000)])
    change = tracker.update(4_000)
    assert change.active == frozenset() and not change.entered and not change.left
    change = tracker.update(5_000)
    assert change.entered == {1} and not change.left
    change = tracker.update(12_000)
    assert not change.entered and not change.left and change.active == {1}
    change = tracker.update(25_000)  # 1 leaves (past +10 s), 2 enters (within -5 s)
    assert change.entered == {2} and change.left == {1}
    change = tracker.update(5_000)  # seeking backwards
    assert change.entered == {1} and change.left == {2}


def test_reset_deactivates_everything() -> None:
    tracker = ActivationTracker([(1, 10_000)])
    tracker.update(10_000)
    change = tracker.reset()
    assert change.left == {1} and tracker.active == frozenset()


def test_note_list_change_is_diffed_on_next_update() -> None:
    tracker = ActivationTracker([(1, 10_000)])
    tracker.update(10_000)
    tracker.set_notes([(1, 10_000), (2, 11_000)])  # a note added at the playhead
    change = tracker.update(10_000)
    assert change.entered == {2} and change.active == {1, 2}
    tracker.set_notes([(2, 11_000)])  # note 1 deleted
    assert tracker.update(10_000).left == {1}
