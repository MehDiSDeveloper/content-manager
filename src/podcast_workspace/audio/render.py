"""Writing a voice out as it sounds in the player: the trimmed pauses left out and the
volume applied, as a new file.

The same `Splicer` the player uses does the cutting (same joins, same fades), so the file
sounds exactly like playback did. ffmpeg decodes to float PCM at the file's own rate and
channel count, Python splices and scales it, and a second ffmpeg encodes it in the
original's format — or in M4A when there is no encoder for that one.

Blocking; run it off the UI thread. `cancel` stops it between chunks and leaves nothing
behind.
"""

import contextlib
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO

import numpy as np

from podcast_workspace.audio.ffmpeg import NO_WINDOW, probe_stream, require_ffmpeg
from podcast_workspace.audio.silence import Span, Splicer

CHUNK_BYTES = 256 * 1024
FALLBACK_SUFFIX = ".m4a"
_WRITABLE = frozenset(
    {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".webm", ".flac", ".wav", ".wma"}
)


class RenderCancelledError(Exception):
    pass


def output_suffix(source: Path) -> str:
    """The rendered file's extension: the original's when it can be written (AMR cannot)."""
    suffix = source.suffix.lower()
    return suffix if suffix in _WRITABLE else FALLBACK_SUFFIX


def trimmed_ms(position_ms: int, cuts: tuple[Span, ...]) -> int:
    """Where `position_ms` of the original lands once `cuts` are left out. A point inside a
    cut lands where the cut was."""
    removed = 0
    for lo, hi in cuts:
        if position_ms <= lo:
            break
        removed += min(position_ms, hi) - lo
    return position_ms - removed


def _codec_args(suffix: str, source_codec: str, channels: int) -> list[str]:
    stereo = channels > 1
    match suffix:
        case ".mp3":
            return ["-c:a", "libmp3lame", "-q:a", "2"]
        case ".m4a" | ".aac":
            return ["-c:a", "aac", "-b:a", "192k" if stereo else "128k"]
        case ".ogg" | ".oga" if source_codec != "opus":
            return ["-c:a", "libvorbis", "-q:a", "5"]
        case ".ogg" | ".oga" | ".opus" | ".webm":
            return ["-c:a", "libopus", "-b:a", "128k" if stereo else "64k", "-ar", "48000"]
        case ".flac":
            return ["-c:a", "flac"]
        case ".wav":
            return ["-c:a", "pcm_s16le"]
        case ".wma":
            return ["-c:a", "wmav2", "-b:a", "192k" if stereo else "128k"]
    raise ValueError(f"cannot write {suffix} files")


def render(
    source: Path,
    target: Path,
    cuts: tuple[Span, ...],
    gain: float = 1.0,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Write `source` to `target` without `cuts` and scaled by `gain` (linear, 0–1).
    `target` appears only once it is complete."""
    info = probe_stream(source)
    rate, channels = info.sample_rate, info.channels
    ffmpeg = str(require_ffmpeg())
    codec = _codec_args(target.suffix.lower(), info.codec, channels)
    partial = target.with_name(f".{target.stem}.partial{target.suffix}")
    frame_bytes = 4 * channels
    total_frames = max(1, info.duration_ms * rate // 1000)
    splicer = Splicer(cuts, 0, 1000 / rate, channels, np.float32)
    scale = np.float32(max(0.0, min(1.0, gain)))

    with tempfile.TemporaryFile() as dec_err, tempfile.TemporaryFile() as enc_err:
        decoder = subprocess.Popen(
            [
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(source), "-map", "0:a:0", "-vn",
                "-ar", str(rate), "-ac", str(channels),
                "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=dec_err,
            creationflags=NO_WINDOW,
        )  # fmt: skip
        encoder = subprocess.Popen(
            [
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "f32le", "-ar", str(rate), "-ac", str(channels), "-i", "pipe:0",
                "-i", str(source), "-map", "0:a", "-map_metadata", "1",
                *codec, "-y", str(partial),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=enc_err,
            creationflags=NO_WINDOW,
        )  # fmt: skip
        assert decoder.stdout is not None and encoder.stdin is not None
        done = False
        try:
            read = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise RenderCancelledError
                chunk = decoder.stdout.read(CHUNK_BYTES)
                if not chunk:
                    break
                read += len(chunk)
                encoder.stdin.write(_scaled(splicer.feed(chunk), scale))
                if on_progress is not None:
                    on_progress(min(1.0, read / frame_bytes / total_frames))
            encoder.stdin.write(_scaled(splicer.flush(), scale))
            encoder.stdin.close()
            decoder.wait()
            encoder.wait()
            if decoder.returncode != 0 or read == 0:
                raise ValueError(_last_line(dec_err) or "decode failed")
            if encoder.returncode != 0:
                raise ValueError(_last_line(enc_err) or "encode failed")
            partial.replace(target)
            done = True
        except (BrokenPipeError, OSError) as exc:
            encoder.wait()
            raise ValueError(_last_line(enc_err) or str(exc)) from exc
        finally:
            for proc in (decoder, encoder):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            with contextlib.suppress(OSError):
                decoder.stdout.close()
                encoder.stdin.close()
            if not done:
                partial.unlink(missing_ok=True)


def _scaled(data: bytes, scale: np.float32) -> bytes:
    if not data or scale == 1:
        return data
    return (np.frombuffer(data, np.float32) * scale).tobytes()


def _last_line(stderr: IO[bytes]) -> str:
    stderr.seek(0)
    lines = stderr.read().decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else ""
