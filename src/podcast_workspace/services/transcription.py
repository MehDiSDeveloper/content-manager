"""Offline Persian transcription of a Voice with faster-whisper (CPU, int8).

The model is a local folder. It is either downloaded once on the user's explicit request
(Settings) or pointed to by the user; transcription itself never touches the network.
faster-whisper is an optional dependency (`pip install .[transcription]`).
"""

import importlib.util
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.audio.ffmpeg import decode_mono_f32
from podcast_workspace.domain.entities import Transcript, TranscriptSegment
from podcast_workspace.paths import models_dir
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.settings_service import SettingsService

# Hugging Face libraries draw tqdm bars on stderr, which is None under pythonw.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

log = logging.getLogger(__name__)

WHISPER_MODELS = ("small", "medium", "large-v3-turbo", "large-v3")
SAMPLE_RATE = 16000
LANGUAGE = "fa"
# Nudges the decoder towards Persian script and punctuation.
INITIAL_PROMPT = "این یک اپیزود پادکست فارسی است."

ProgressCallback = Callable[[float], None]


class TranscriptionUnavailableError(RuntimeError):
    """faster-whisper is not installed."""


class ModelMissingError(RuntimeError):
    """No local model folder; the user has to download or choose one first."""


class TranscriptionCancelledError(Exception):
    pass


def whisper_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _is_model_dir(path: Path) -> bool:
    return (path / "model.bin").is_file() and (path / "config.json").is_file()


class TranscriptionService:
    """One transcription at a time (it saturates the CPU); the loaded model is kept."""

    def __init__(self, session_factory: sessionmaker[Session], settings: SettingsService) -> None:
        self._sf = session_factory
        self._settings = settings
        self._lock = threading.Lock()
        self._model: Any = None
        self._model_key: str | None = None

    # stored transcripts ----------------------------------------------------------------
    def get(self, voice_id: int) -> Transcript | None:
        with UnitOfWork(self._sf) as uow:
            return uow.transcripts.for_voice(voice_id)

    def voice_ids(self) -> set[int]:
        with UnitOfWork(self._sf) as uow:
            return uow.transcripts.voice_ids()

    def delete(self, voice_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            existing = uow.transcripts.for_voice(voice_id)
            if existing is not None and existing.id is not None:
                uow.transcripts.delete(existing.id)

    # model -----------------------------------------------------------------------------
    def managed_model_dir(self, name: str | None = None) -> Path:
        return models_dir() / f"faster-whisper-{name or self._settings.whisper_model()}"

    def is_downloaded(self, name: str) -> bool:
        return _is_model_dir(self.managed_model_dir(name))

    def model_path(self) -> Path | None:
        custom = self._settings.whisper_model_dir()
        if custom:
            path = Path(custom)
            return path if _is_model_dir(path) else None
        managed = self.managed_model_dir()
        return managed if _is_model_dir(managed) else None

    def download_model(self, name: str) -> Path:
        """One-time download of a model (network). Only on the user's explicit request."""
        if not whisper_installed():
            raise TranscriptionUnavailableError
        from faster_whisper.utils import download_model

        target = self.managed_model_dir(name)
        download_model(name, output_dir=str(target))
        if not _is_model_dir(target):
            raise ModelMissingError(str(target))
        return target

    def _load(self, path: Path) -> Any:
        key = str(path.resolve())
        if self._model is None or self._model_key != key:
            from faster_whisper import WhisperModel

            self._model = None  # free the old one before loading another
            threads = max(1, (os.cpu_count() or 2) - 1)
            self._model = WhisperModel(
                key,
                device="cpu",
                compute_type="int8",
                cpu_threads=threads,
                local_files_only=True,
            )
            self._model_key = key
        return self._model

    # run -------------------------------------------------------------------------------
    def transcribe(
        self,
        voice_id: int,
        on_progress: ProgressCallback,
        cancel: threading.Event,
    ) -> Transcript:
        """Blocking; call it off the UI thread. Replaces any earlier transcript."""
        if not whisper_installed():
            raise TranscriptionUnavailableError
        path = self.model_path()
        if path is None:
            raise ModelMissingError(
                self._settings.whisper_model_dir() or self._settings.whisper_model()
            )
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
        audio_file = Path(voice.file_path)
        if not audio_file.is_file():
            raise FileNotFoundError(audio_file)

        with self._lock:
            on_progress(0.0)
            model = self._load(path)
            if cancel.is_set():
                raise TranscriptionCancelledError
            audio = np.frombuffer(decode_mono_f32(audio_file, SAMPLE_RATE), dtype=np.float32)
            total_s = max(len(audio) / SAMPLE_RATE, 0.001)
            segments, _info = model.transcribe(
                audio,
                language=LANGUAGE,
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,  # avoids runaway repetition loops
                initial_prompt=INITIAL_PROMPT,
            )
            collected: list[TranscriptSegment] = []
            for segment in segments:  # decoding happens lazily, segment by segment
                if cancel.is_set():
                    raise TranscriptionCancelledError
                collected.append(
                    TranscriptSegment(
                        int(segment.start * 1000), int(segment.end * 1000), segment.text
                    )
                )
                on_progress(min(1.0, segment.end / total_s))

        transcript = Transcript(voice_id=voice_id, segments=collected, model=path.name)
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(voice_id)  # the voice may have been removed meanwhile
            stored = uow.transcripts.replace(transcript)
        on_progress(1.0)
        log.info("transcribed voice %s: %d segments", voice_id, len(stored.segments))
        return stored
