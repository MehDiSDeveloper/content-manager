import numpy as np
import pytest

from podcast_workspace.audio.silence import (
    EDGE_MS,
    MAX_KEEP_MS,
    MIN_CUT_MS,
    Splicer,
    clamp_keep,
    cuts_for,
    find_pauses,
    total_ms,
)
from podcast_workspace.audio.waveform import Waveform

BUCKET_MS = 10.0


def _waveform(pattern: list[tuple[str, int]], noise: float = 0.002) -> Waveform:
    """Buckets from ("speech"|"quiet", ms) stretches; speech varies a little like voices do."""
    rng = np.random.default_rng(7)
    rms: list[float] = []
    for kind, ms in pattern:
        n = int(ms / BUCKET_MS)
        level = rng.uniform(0.08, 0.3, n) if kind == "speech" else rng.uniform(0.5, 1.5, n) * noise
        rms.extend(level)
    values = np.array(rms, dtype=np.float32)
    peaks = np.stack((np.minimum(values * 3, 1.0), values), axis=1)
    return Waveform(peaks, BUCKET_MS, int(len(values) * BUCKET_MS))


# detection ---------------------------------------------------------------------------------
def test_pauses_between_words_are_found():
    wave = _waveform([("speech", 2000), ("quiet", 1500), ("speech", 2000), ("quiet", 800)] * 2)
    pauses = find_pauses(wave)
    assert pauses[:3] == ((2000, 3500), (5500, 6300), (8300, 9800))


def test_short_gaps_inside_speech_are_not_pauses():
    wave = _waveform([("speech", 1500), ("quiet", 100), ("speech", 1500), ("quiet", 1000)] * 3)
    assert all(end - start >= 1000 for start, end in find_pauses(wave))


def test_a_click_does_not_split_a_pause():
    wave = _waveform([("speech", 2000), ("quiet", 600), ("speech", 20), ("quiet", 600)] * 3)
    assert (2000, 3220) in find_pauses(wave)


def test_a_blip_right_before_a_word_is_kept():
    # 20 ms of sound 80 ms before the next word: likely a consonant's burst, not a click.
    wave = _waveform([("speech", 2000), ("quiet", 800), ("speech", 20), ("quiet", 80)] * 3)
    pauses = find_pauses(wave)
    assert (2000, 2800) in pauses
    assert all(not (start < 2810 < end) for start, end in pauses)


def test_noisy_room_still_works():
    wave = _waveform([("speech", 2000), ("quiet", 1000)] * 4, noise=0.02)
    assert len(find_pauses(wave)) == 4


def test_no_contrast_means_no_pauses():
    flat = np.full((500, 2), 0.1, dtype=np.float32)
    assert find_pauses(Waveform(flat, BUCKET_MS, 5000)) == ()


def test_digital_silence_does_not_drag_the_threshold_down():
    # Zero padding at the start must not make the room noise between words count as speech.
    wave = _waveform([("speech", 2000), ("quiet", 1000)] * 4, noise=0.01)
    padded = np.concatenate((np.zeros((300, 2), np.float32), wave.peaks))
    pauses = find_pauses(Waveform(padded, BUCKET_MS, wave.duration_ms + 3000))
    assert (5000, 6000) in pauses


# cuts --------------------------------------------------------------------------------------
def test_keep_leaves_half_on_each_side():
    assert cuts_for(((2000, 5000),), 500, 10_000) == ((2250, 4750),)


def test_pause_shorter_than_keep_is_left_alone():
    assert cuts_for(((2000, 2400),), 500, 10_000) == ()
    assert cuts_for(((2000, 2400),), 2000, 10_000) == ()


def test_zero_keep_still_leaves_the_word_edges():
    (cut,) = cuts_for(((2000, 3000),), 0, 10_000)
    assert cut == (2000 + EDGE_MS, 3000 - EDGE_MS)


def test_tiny_cuts_are_skipped():
    length = 500 + MIN_CUT_MS - 1
    assert cuts_for(((2000, 2000 + length),), 500, 10_000) == ()


def test_leading_and_trailing_silence_keep_only_the_speech_side():
    cuts = cuts_for(((0, 3000), (7000, 10_000)), 1000, 10_000)
    assert cuts == ((0, 2500), (7500, 10_000))


def test_saving_grows_as_keep_shrinks():
    pauses = ((1000, 3000), (5000, 5800), (9000, 11_500))
    savings = [total_ms(cuts_for(pauses, keep, 20_000)) for keep in (0, 500, 1000, 2000)]
    assert savings == sorted(savings, reverse=True)
    assert savings[-1] == 500  # only the 2.5 s pause is longer than 2 s


@pytest.mark.parametrize(("raw", "snapped"), [(-5, 0), (26, 50), (510, 500), (9000, MAX_KEEP_MS)])
def test_keep_is_snapped_to_the_slider(raw, snapped):
    assert clamp_keep(raw) == snapped


# splicing ----------------------------------------------------------------------------------
RATE = 1000  # one frame per millisecond keeps the arithmetic readable


def _stream(ms: int, channels: int = 1) -> np.ndarray:
    frames = np.arange(1, ms + 1, dtype=np.float32) / 10_000  # never zero, strictly rising
    return np.repeat(frames[:, None], channels, axis=1)


def _run(splicer: Splicer, audio: np.ndarray, chunk_frames: int) -> np.ndarray:
    raw = audio.astype(audio.dtype).tobytes()
    step = chunk_frames * audio.shape[1] * audio.dtype.itemsize
    out = b"".join(splicer.feed(raw[i : i + step]) for i in range(0, len(raw), step))
    out += splicer.flush()
    return np.frombuffer(out, audio.dtype).reshape(-1, audio.shape[1])


def test_no_cuts_passes_everything_through():
    audio = _stream(500, channels=2)
    out = _run(Splicer((), 0, 1000 / RATE, 2, np.float32), audio, 64)
    assert np.array_equal(out, audio)


@pytest.mark.parametrize("chunk", [7, 64, 100, 1000])
def test_cut_frames_are_left_out_whatever_the_chunking(chunk):
    audio = _stream(1000)
    splicer = Splicer(((200, 500), (700, 750)), 0, 1000 / RATE, 1, np.float32)
    out = _run(splicer, audio, chunk)
    assert len(out) == 1000 - 300 - 50
    kept = np.concatenate((audio[:200], audio[500:700], audio[750:]))
    fade = round(6 * RATE / 1000)
    # Away from the joins the audio is untouched; at a join it only ever gets quieter.
    assert np.array_equal(out[: 200 - fade], kept[: 200 - fade])
    assert np.array_equal(out[210:390], kept[210:390])
    assert np.all(out <= kept + 1e-7)
    assert out[199, 0] < kept[199, 0] / 2  # faded out into the cut
    assert out[200, 0] < kept[200, 0] / 2  # and back in after it


def test_positions_map_back_to_the_file_timeline():
    splicer = Splicer(((200, 500),), 0, 1000 / RATE, 1, np.float32)
    _run(splicer, _stream(1000), 50)
    assert splicer.source_ms(100) == 100
    assert splicer.source_ms(200) == 500  # the first frame after the join
    assert splicer.source_ms(450) == 750


def test_a_segment_starting_mid_file_and_inside_a_cut():
    # A seek to 3.3 s lands inside the cut 3.0–3.6 s: playback starts at 3.6 s.
    splicer = Splicer(((3000, 3600), (4000, 4200)), 3300, 1000 / RATE, 1, np.float32)
    out = _run(splicer, _stream(1000), 128)
    assert len(out) == 1000 - 300 - 200
    assert splicer.source_ms(0) == 3600
    assert splicer.source_ms(400) == 4200


def test_speed_scales_the_timeline():
    # At 2× each output frame covers 2 ms of the file.
    splicer = Splicer(((400, 1000),), 0, 2 * 1000 / RATE, 1, np.float32)
    out = _run(splicer, _stream(1000), 64)
    assert len(out) == 1000 - 300
    assert splicer.source_ms(200) == 1000


def test_int16_output_is_faded_in_place():
    audio = np.full((600, 2), 8000, dtype=np.int16)
    out = _run(Splicer(((200, 400),), 0, 1000 / RATE, 2, np.int16), audio, 33)
    assert out.dtype == np.int16 and len(out) == 400
    assert out[0, 0] == 8000 and out[-1, 1] == 8000
    assert 0 < out[200, 0] < 8000
