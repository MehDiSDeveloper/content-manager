"""Pause trimming for playback: find the quiet stretches in a waveform, decide how much of
each to skip, and splice a decoded stream around them.

The file is never touched. The player plays the original with the cut stretches left out,
and every position it reports stays on the file's own timeline, so timestamp notes, the
transcript and the waveform line up exactly as they do without trimming.

Detection reads the waveform's per-bucket RMS (~10 ms). The threshold sits between the
recording's own noise floor and its speech level, so a quiet room and a noisy one both work
without a knob. A recording with no clear gap between the two (music, constant noise) gets
no pauses at all rather than a guess.
"""

import bisect
import math

import numpy as np

from podcast_workspace.audio.waveform import Waveform

type Span = tuple[int, int]  # [start_ms, end_ms) on the file's timeline

MAX_KEEP_MS = 2000
KEEP_STEP_MS = 50
DEFAULT_KEEP_MS = 500
# Silence always left against speech on each side, whatever the setting: word tails and
# soft onsets (س, ف, breathy vowels) fall under the threshold and would be clipped. So a
# pause never gets shorter than twice this, even at «0».
EDGE_MS = 40
MIN_CUT_MS = 40  # a shorter cut saves nothing audible and only adds a join
FADE_MS = 6  # each join fades out and back in over this, so a cut never clicks

_SILENT_DB = -100.0  # level given to digital silence (log of zero)
_DIGITAL_SILENCE_DB = -90.0  # below this a bucket is padding, not room noise
_FLOOR_PERCENTILE = 10
_SPEECH_PERCENTILE = 95
_MIN_CONTRAST_DB = 12.0  # speech must stand this far above the floor to trust any pause
_THRESHOLD_SHARE = 0.3  # threshold = floor + this share of the floor→speech distance
# A click this short does not split a pause, as long as it sits well inside it: a blip
# close to a word is more likely the burst of a consonant (ت, پ) than a mouth noise.
_MAX_BLIP_MS = 30
_BLIP_CLEARANCE_MS = 150


def clamp_keep(keep_ms: int) -> int:
    """The setting snapped to the slider's steps and range."""
    snapped = round(keep_ms / KEEP_STEP_MS) * KEEP_STEP_MS
    return max(0, min(MAX_KEEP_MS, snapped))


def find_pauses(waveform: Waveform) -> tuple[Span, ...]:
    """Every quiet stretch long enough that some keep setting could shorten it."""
    if not waveform.buckets or waveform.duration_ms <= 0:
        return ()
    rms = waveform.peaks[:, 1].astype(np.float64)
    level = 20 * np.log10(np.maximum(rms, 10 ** (_SILENT_DB / 20)))
    live = level[level > _DIGITAL_SILENCE_DB]
    if live.size == 0:
        return ()
    floor = float(np.percentile(live, _FLOOR_PERCENTILE))
    speech = float(np.percentile(live, _SPEECH_PERCENTILE))
    if speech - floor < _MIN_CONTRAST_DB:
        return ()
    quiet = level < floor + (speech - floor) * _THRESHOLD_SHARE

    blip = max(1, round(_MAX_BLIP_MS / waveform.bucket_ms))
    clearance = round(_BLIP_CLEARANCE_MS / waveform.bucket_ms)
    sounds = _runs(~quiet)
    for k, (start, end) in enumerate(sounds):
        if end - start > blip or k == 0 or k == len(sounds) - 1:
            continue
        if start - sounds[k - 1][1] >= clearance and sounds[k + 1][0] - end >= clearance:
            quiet[start:end] = True

    shortest = 2 * EDGE_MS + MIN_CUT_MS
    pauses: list[Span] = []
    for start, end in _runs(quiet):
        start_ms = round(start * waveform.bucket_ms)
        end_ms = min(waveform.duration_ms, round(end * waveform.bucket_ms))
        if end_ms - start_ms >= shortest:
            pauses.append((start_ms, end_ms))
    return tuple(pauses)


def cuts_for(pauses: tuple[Span, ...], keep_ms: int, duration_ms: int) -> tuple[Span, ...]:
    """The stretches to skip so that no pause lasts longer than `keep_ms`.

    Each pause keeps half the allowance against the speech on either side, so what is left
    sounds like a shorter pause, not a join. Silence before the first word and after the
    last one keeps only the half that faces speech.
    """
    half = max(clamp_keep(keep_ms), 2 * EDGE_MS) // 2
    cuts: list[Span] = []
    for start, end in pauses:
        lo = 0 if start <= 0 else start + half
        hi = duration_ms if duration_ms > 0 and end >= duration_ms else end - half
        if hi - lo >= MIN_CUT_MS:
            cuts.append((lo, hi))
    return tuple(cuts)


def total_ms(spans: tuple[Span, ...]) -> int:
    return sum(end - start for start, end in spans)


def _runs(mask: np.ndarray) -> np.ndarray:
    """[start, end) index pairs of the True stretches in `mask`."""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return np.stack((np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)), axis=1)


class Splicer:
    """Leaves the cut stretches out of a decoded PCM stream as it passes through.

    Takes raw interleaved frames (float32 or int16) that begin at `start_ms` on the file's
    timeline, each frame covering `ms_per_frame` of it (1000 × speed / output rate). Every
    join fades out and back in. The last few frames of each call are held back until the
    next one, so a cut that begins right at a chunk boundary can still fade what came
    before it. `source_ms` maps a frame of the output back to the file's timeline.
    """

    def __init__(
        self,
        cuts: tuple[Span, ...],
        start_ms: int,
        ms_per_frame: float,
        channels: int,
        dtype: type[np.generic],
    ) -> None:
        self._dtype = np.dtype(dtype)
        self._channels = channels
        self._frame_bytes = channels * self._dtype.itemsize
        self._ms_per_frame = ms_per_frame
        self._start_ms = start_ms
        self._cuts = [
            (max(0, round((lo - start_ms) / ms_per_frame)), round((hi - start_ms) / ms_per_frame))
            for lo, hi in cuts
            if hi > start_ms
        ]
        self._next_cut = 0
        fade = max(1, round(FADE_MS / ms_per_frame))
        self._ramp = (0.5 - 0.5 * np.cos(np.linspace(0, math.pi, fade + 2)[1:-1]))[:, None]
        self._fade_in_done = fade
        self._in = 0  # source frames consumed
        self._out = 0  # frames handed out, held ones included
        self._marks: list[tuple[int, float]] = [(0, float(start_ms))]  # (out frame, source ms)
        self._partial = b""
        self._hold = np.empty((0, channels), self._dtype)
        self._cutting = False

    def feed(self, data: bytes) -> bytes:
        data = self._partial + data
        usable = len(data) - len(data) % self._frame_bytes
        self._partial = data[usable:]
        count = usable // self._frame_bytes
        if count == 0:
            return b""
        if self._next_cut >= len(self._cuts) and not self._hold.size and not self._cutting:
            self._in += count  # nothing left to cut: pass straight through
            self._out += count
            return data[:usable]
        frames = np.frombuffer(data[:usable], self._dtype).reshape(-1, self._channels)
        return self._splice(frames).tobytes()

    def flush(self) -> bytes:
        """The held-back tail, at the end of the stream."""
        held, self._hold = self._hold, self._hold[:0]
        return held.tobytes()

    def source_ms(self, out_frame: int) -> float:
        """Where on the file's timeline the output's `out_frame` came from."""
        index = bisect.bisect_right(self._marks, out_frame, key=lambda mark: mark[0]) - 1
        mark_out, mark_ms = self._marks[max(0, index)]
        return mark_ms + (out_frame - mark_out) * self._ms_per_frame

    def _splice(self, frames: np.ndarray) -> np.ndarray:
        pending = self._hold
        base = self._in
        pos, end = base, base + len(frames)
        while pos < end:
            cut = self._cut_from(pos)
            if cut is not None and cut[0] <= pos:  # inside a cut: skip to its end
                if not self._cutting:
                    self._cutting = True
                    pending = self._fade_out(pending)
                pos = min(cut[1], end)
                continue
            stop = end if cut is None else min(cut[0], end)
            piece = frames[pos - base : stop - base]
            if self._cutting:
                self._cutting = False
                self._fade_in_done = 0
                self._marks.append((self._out, self._start_ms + pos * self._ms_per_frame))
            if self._fade_in_done < len(self._ramp):
                piece = self._fade_in(piece)
            pending = np.concatenate((pending, piece))
            self._out += len(piece)
            pos = stop
        self._in = end
        held = min(len(self._ramp), len(pending))
        self._hold = pending[len(pending) - held :].copy()
        return pending[: len(pending) - held]

    def _cut_from(self, pos: int) -> tuple[int, int] | None:
        """The first cut that has not ended by source frame `pos`."""
        while self._next_cut < len(self._cuts) and self._cuts[self._next_cut][1] <= pos:
            self._next_cut += 1
        return self._cuts[self._next_cut] if self._next_cut < len(self._cuts) else None

    def _fade_out(self, pending: np.ndarray) -> np.ndarray:
        n = min(len(self._ramp), len(pending))
        if n == 0:
            return pending
        pending = pending.copy()
        pending[-n:] = self._scaled(pending[-n:], self._ramp[::-1][-n:])
        return pending

    def _fade_in(self, piece: np.ndarray) -> np.ndarray:
        n = min(len(self._ramp) - self._fade_in_done, len(piece))
        piece = piece.copy()
        ramp = self._ramp[self._fade_in_done : self._fade_in_done + n]
        piece[:n] = self._scaled(piece[:n], ramp)
        self._fade_in_done += n
        return piece

    def _scaled(self, block: np.ndarray, ramp: np.ndarray) -> np.ndarray:
        scaled = block * ramp
        if self._dtype.kind == "i":
            scaled = np.rint(scaled)
        return scaled.astype(self._dtype)
