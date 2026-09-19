"""Locate the bundled ffmpeg and read stream parameters of an audio file.

Lookup order: resources/bin/ffmpeg.exe (drop-in for packaging), the binary shipped by the
`imageio-ffmpeg` wheel, then PATH.
"""

import functools
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from podcast_workspace.paths import resources_dir

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_LAYOUT_CHANNELS = {
    "mono": 1,
    "stereo": 2,
    "2.1": 3,
    "3.0": 3,
    "quad": 4,
    "4.0": 4,
    "5.0": 5,
    "5.1": 6,
    "6.1": 7,
    "7.1": 8,
}
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_AUDIO_STREAM = re.compile(r"Stream #\d+:\d+.*?: Audio: ([^,\s]+)[^,]*, (\d+) Hz, ([^,]+)")


class FfmpegMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamInfo:
    sample_rate: int
    channels: int
    duration_ms: int  # 0 when the container does not say
    codec: str


@functools.cache
def ffmpeg_path() -> Path | None:
    bundled = resources_dir() / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return bundled
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError):
        pass
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


@functools.cache
def ffprobe_path() -> Path | None:
    bundled = resources_dir() / "bin" / "ffprobe.exe"
    if bundled.exists():
        return bundled
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def require_ffmpeg() -> Path:
    path = ffmpeg_path()
    if path is None:
        raise FfmpegMissingError("ffmpeg not found")
    return path


@functools.cache
def has_filter(name: str) -> bool:
    """True if this ffmpeg build has the named filter/resampler option (e.g. soxr)."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        return False
    if name == "soxr":
        args = [str(ffmpeg), "-hide_banner", "-buildconf"]
        needle = "--enable-libsoxr"
    else:
        args = [str(ffmpeg), "-hide_banner", "-filters"]
        needle = f" {name} "
    try:
        out = subprocess.run(
            args, capture_output=True, timeout=10, check=False, creationflags=NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return needle in out.stdout.decode("utf-8", "replace")


def probe_stream(path: Path) -> StreamInfo:
    """Parameters of the first audio stream. Raises ValueError if there is none."""
    ffprobe = ffprobe_path()
    if ffprobe is not None:
        info = _probe_with_ffprobe(ffprobe, path)
        if info is not None:
            return info
    return _probe_with_ffmpeg(require_ffmpeg(), path)


def _probe_with_ffprobe(ffprobe: Path, path: Path) -> StreamInfo | None:
    args = [
        str(ffprobe),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.run(
            args, capture_output=True, timeout=20, check=True, creationflags=NO_WINDOW
        )
        data = json.loads(out.stdout)
        stream = data["streams"][0]
        duration = float(data.get("format", {}).get("duration") or 0)
        return StreamInfo(
            int(stream["sample_rate"]),
            int(stream["channels"]),
            int(duration * 1000),
            stream.get("codec_name", ""),
        )
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError):
        return None


def _probe_with_ffmpeg(ffmpeg: Path, path: Path) -> StreamInfo:
    # With no output file ffmpeg prints the input description to stderr and exits 1.
    out = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=NO_WINDOW,
    )
    text = out.stderr.decode("utf-8", "replace")
    stream = _AUDIO_STREAM.search(text)
    if stream is None:
        raise ValueError(f"no audio stream in {path.name}")
    codec, rate, layout = stream.group(1), int(stream.group(2)), stream.group(3).strip()
    channels = _LAYOUT_CHANNELS.get(layout.split("(")[0])
    if channels is None:
        match = re.match(r"(\d+) channels", layout)
        channels = int(match.group(1)) if match else 2
    duration_ms = 0
    found = _DURATION.search(text)
    if found:
        h, m, s = found.groups()
        duration_ms = int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
    return StreamInfo(rate, channels, duration_ms, codec)


def decode_mono_f32(path: Path, sample_rate: int = 16000) -> bytes:
    """Whole file as mono float32 PCM at `sample_rate` (raw little-endian bytes).

    Used by transcription; an hour of 16 kHz audio is ~230 MB.
    """
    args = [
        str(require_ffmpeg()),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ]
    out = subprocess.run(args, capture_output=True, check=False, creationflags=NO_WINDOW)
    if out.returncode != 0 or not out.stdout:
        message = out.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(message[-1] if message else f"ffmpeg exited with {out.returncode}")
    return out.stdout
