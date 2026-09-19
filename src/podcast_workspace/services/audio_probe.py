"""Read duration/format of an audio file through ffmpeg; stdlib fallback for WAV."""

import wave
from dataclasses import dataclass
from pathlib import Path

from podcast_workspace.audio.ffmpeg import FfmpegMissingError, probe_stream

SUPPORTED_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".webm", ".amr"}
)


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int
    format: str


def probe(path: Path) -> AudioInfo:
    if not path.is_file():
        raise FileNotFoundError(path)
    fmt = path.suffix.lower().lstrip(".")
    try:
        info = probe_stream(path)
    except (FfmpegMissingError, ValueError, OSError):
        info = None
    if info is not None and info.duration_ms > 0:
        return AudioInfo(info.duration_ms, fmt)
    if fmt == "wav":
        try:
            with wave.open(str(path), "rb") as wav:
                return AudioInfo(int(wav.getnframes() * 1000 / wav.getframerate()), fmt)
        except (wave.Error, EOFError, ZeroDivisionError):
            pass  # compressed or odd WAV variant
    return AudioInfo(0, fmt)  # unknown; the waveform pass fills in the exact duration
