"""Waveform extraction: one full ffmpeg decode -> peak/RMS per ~10 ms bucket, cached on disk.

Blocking; run it off the UI thread. The decode also yields the exact duration.

Seek cache: ffmpeg's demuxers seek sample-exactly in wav/flac/aac/vorbis/opus but land up to
~70 ms off in VBR mp3 and wma. For those, the same pass writes a lossless FLAC copy of the
decoded audio (16-bit, triangular dither) that the player decodes from instead.
"""

import contextlib
import hashlib
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from podcast_workspace.audio.ffmpeg import NO_WINDOW, probe_stream, require_ffmpeg
from podcast_workspace.paths import data_dir

BUCKETS_PER_SECOND = 100
CACHE_VERSION = 1
EXACT_SEEK_FORMATS = frozenset({"wav", "flac", "m4a", "aac", "ogg", "oga", "opus"})
SEEK_CACHE_LIMIT_BYTES = 4 * 1024**3
PROGRESS_INTERVAL_S = 0.25


@dataclass(frozen=True)
class Waveform:
    peaks: np.ndarray  # float32, shape (n, 2): [abs peak, rms] per bucket, 0..1
    bucket_ms: float
    duration_ms: int
    complete: bool = True

    @property
    def buckets(self) -> int:
        return int(self.peaks.shape[0])


class ExtractionCancelledError(Exception):
    pass


def _cache_file(path: Path, suffix: str = ".npz") -> Path:
    stat = path.stat()
    key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{CACHE_VERSION}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    folder = data_dir() / "cache" / "waveforms"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}{suffix}"


def needs_seek_cache(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") not in EXACT_SEEK_FORMATS


def seek_cache(path: Path) -> Path | None:
    """The FLAC copy to decode from for exact seeking, if this file needs and has one."""
    if not needs_seek_cache(path):
        return None
    try:
        cache = _cache_file(path, ".flac")
    except OSError:
        return None
    if cache.exists():
        cache.touch()  # LRU
        return cache
    return None


def _prune_seek_cache(keep: Path) -> None:
    files = sorted(keep.parent.glob("*.flac"), key=lambda f: f.stat().st_mtime, reverse=True)
    total = 0
    for file in files:
        total += file.stat().st_size
        if total > SEEK_CACHE_LIMIT_BYTES and file != keep:
            file.unlink(missing_ok=True)


def load_cached(path: Path) -> Waveform | None:
    try:
        cache = _cache_file(path)
        if not cache.exists():
            return None
        with np.load(cache) as data:
            return Waveform(
                data["peaks"].astype(np.float32),
                float(data["bucket_ms"]),
                int(data["duration_ms"]),
            )
    except (OSError, ValueError, KeyError):
        return None


def extract(
    path: Path,
    cancel: threading.Event,
    on_progress: Callable[[Waveform], None] | None = None,
) -> Waveform:
    cached = load_cached(path)
    want_seek_cache = needs_seek_cache(path) and seek_cache(path) is None
    if cached is not None and not want_seek_cache:
        return cached
    info = probe_stream(path)
    rate = info.sample_rate
    bucket = max(1, rate // BUCKETS_PER_SECOND)
    bucket_ms = bucket * 1000 / rate
    chunk_floats = bucket * 500  # 5 s of mono audio per read
    seek_cache_args: list[str] = []
    partial_flac: Path | None = None
    if want_seek_cache:
        partial_flac = _cache_file(path, ".part.flac")
        seek_cache_args = [
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "aresample=dither_method=triangular",
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            "-y",
            str(partial_flac),
        ]
    proc = subprocess.Popen(
        [
            str(require_ffmpeg()),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
            *seek_cache_args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    assert proc.stdout is not None
    parts: list[np.ndarray] = []
    carry = np.empty(0, dtype=np.float32)
    total_samples = 0
    last_report = time.monotonic()
    try:
        while True:
            if cancel.is_set():
                raise ExtractionCancelledError
            raw = proc.stdout.read(chunk_floats * 4)
            if not raw:
                break
            usable = len(raw) - len(raw) % 4
            samples = np.frombuffer(raw[:usable], dtype=np.float32)
            total_samples += samples.size
            data = np.concatenate((carry, samples)) if carry.size else samples
            whole = data.size - data.size % bucket
            carry = data[whole:].copy()
            if whole:
                parts.append(_reduce(data[:whole].reshape(-1, bucket)))
            now = time.monotonic()
            if on_progress is not None and now - last_report >= PROGRESS_INTERVAL_S:
                last_report = now
                partial = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
                duration = max(info.duration_ms, int(total_samples * 1000 / rate))
                on_progress(Waveform(partial, bucket_ms, duration, complete=False))
        if carry.size:
            parts.append(_reduce(carry.reshape(1, -1)))
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if partial_flac is not None and proc.returncode != 0:
            partial_flac.unlink(missing_ok=True)
    if proc.returncode != 0 and total_samples == 0:
        assert proc.stderr is not None
        raise ValueError(proc.stderr.read().decode("utf-8", "replace").strip() or "decode failed")
    peaks = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
    waveform = Waveform(peaks, bucket_ms, round(total_samples * 1000 / rate))
    with contextlib.suppress(OSError):  # the cache is an optimisation only
        np.savez(
            _cache_file(path),
            peaks=peaks.astype(np.float16),
            bucket_ms=bucket_ms,
            duration_ms=waveform.duration_ms,
        )
    if partial_flac is not None and proc.returncode == 0:
        final = _cache_file(path, ".flac")
        try:
            partial_flac.replace(final)
            _prune_seek_cache(final)
        except OSError:
            partial_flac.unlink(missing_ok=True)
    return waveform


def _reduce(blocks: np.ndarray) -> np.ndarray:
    peak = np.abs(blocks).max(axis=1)
    rms = np.sqrt(np.mean(np.square(blocks, dtype=np.float64), axis=1))
    return np.minimum(np.stack((peak, rms), axis=1), 1.0).astype(np.float32)
