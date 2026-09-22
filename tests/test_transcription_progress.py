"""The clock estimate that moves the transcription bar between decoded windows."""

from podcast_workspace.services.transcription import (
    ESTIMATE_CEILING,
    ESTIMATE_KNEE,
    FALLBACK_SPEED,
    default_speed,
    estimated_fraction,
)


def test_linear_up_to_the_knee():
    assert estimated_fraction(0, 100) == 0
    assert estimated_fraction(50, 100) == 0.5
    assert estimated_fraction(ESTIMATE_KNEE * 100, 100) == ESTIMATE_KNEE


def test_keeps_moving_but_never_finishes_when_the_guess_was_short():
    late = [estimated_fraction(t, 100) for t in (90, 120, 200, 400, 1000)]
    assert late == sorted(late)
    assert len(set(late)) == len(late)
    assert all(ESTIMATE_KNEE < f < ESTIMATE_CEILING for f in late)


def test_no_expectation_no_estimate():
    assert estimated_fraction(10, 0) == 0


def test_default_speed_from_the_folder_name():
    assert default_speed("faster-whisper-large-v3-turbo") < default_speed("faster-whisper-large-v3")
    assert default_speed("faster-whisper-small") < default_speed("faster-whisper-medium")
    assert default_speed("my-own-model") == FALLBACK_SPEED
