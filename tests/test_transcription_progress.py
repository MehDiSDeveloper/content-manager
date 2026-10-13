"""The clock estimate that moves the transcription bar between decoded windows, and the
model being let go once it sits unused."""

import time

from podcast_workspace.services.transcription import (
    ESTIMATE_CEILING,
    ESTIMATE_KNEE,
    FALLBACK_SPEED,
    MODEL_IDLE_RELEASE_S,
    TranscriptionService,
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


def _loaded_service(idle_s: float) -> TranscriptionService:
    service = TranscriptionService(None, None)  # type: ignore[arg-type]  # no DB needed
    service._model, service._model_key = object(), "model"
    service._last_used = time.monotonic() - idle_s
    return service


def test_the_model_stays_while_recently_used():
    service = _loaded_service(idle_s=MODEL_IDLE_RELEASE_S / 2)
    assert not service.release_if_idle()
    assert service._model is not None


def test_the_model_goes_once_unused_long_enough():
    service = _loaded_service(idle_s=MODEL_IDLE_RELEASE_S + 1)
    assert service.release_if_idle()
    assert service._model is None and service._model_key is None


def test_a_running_job_keeps_the_model():
    service = _loaded_service(idle_s=MODEL_IDLE_RELEASE_S + 1)
    with service._lock:  # what transcribe() holds while it runs
        assert not service.release_if_idle()
    assert service._model is not None
