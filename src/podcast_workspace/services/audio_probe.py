"""Read duration/format of an audio file with ffprobe; stdlib fallback for WAV."""

import json
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from podcast_workspace.paths import resources_dir

SUPPORTED_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".webm", ".amr"}
)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int
    format: str


def ffprobe_path() -> Path | None:
    bundled = resources_dir() / "bin" / "ffprobe.exe"
    if bundled.exists():
        return bundled
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def probe(path: Path) -> AudioInfo:
    if not path.is_file():
        raise FileNotFoundError(path)
    fmt = path.suffix.lower().lstrip(".")
    ffprobe = ffprobe_path()
    if ffprobe is not None:
        duration = _ffprobe_duration(ffprobe, path)
        if duration is not None:
            return AudioInfo(duration, fmt)
    if fmt == "wav":
        try:
            with wave.open(str(path), "rb") as wav:
                return AudioInfo(int(wav.getnframes() * 1000 / wav.getframerate()), fmt)
        except (wave.Error, EOFError, ZeroDivisionError):
            pass  # compressed or odd WAV variant; duration stays unknown
    return AudioInfo(0, fmt)  # unknown until ffmpeg is bundled; playback can fill it in


def _ffprobe_duration(ffprobe: Path, path: Path) -> int | None:
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=20,
            check=True,
            creationflags=_NO_WINDOW,
        )
        seconds = float(json.loads(result.stdout)["format"]["duration"])
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None
    return int(seconds * 1000)
