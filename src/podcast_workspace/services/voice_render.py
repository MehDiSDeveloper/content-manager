"""Saving a voice as it sounds in the player: pauses trimmed, volume applied.

The result is either a new voice beside the original («name 01») carrying its tags,
timestamp notes and transcript, or the same voice with its audio replaced. Either way
every note and transcript line keeps pointing at the same words: their times are moved
back by the pauses cut before them (`audio/render.trimmed_ms`).

Neither is recorded for undo. A new copy is additive (like an import; it can go to the
trash), and a replacement writes over the old audio, which the UI says before asking.

The Bale bot uses `trimmed_for_sending` for the same trimming, with the remembered pause
setting, into a throwaway file.
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.audio.render import output_suffix, render, trimmed_ms
from podcast_workspace.audio.silence import Span, cuts_for, find_pauses, total_ms
from podcast_workspace.audio.waveform import extract
from podcast_workspace.domain.entities import (
    TimestampNote,
    Transcript,
    TranscriptSegment,
    Voice,
    utcnow,
)
from podcast_workspace.paths import voices_dir
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.audio_probe import probe
from podcast_workspace.services.voice_store import discard, free_name, is_stored, name_key

log = logging.getLogger(__name__)

SWAP_ATTEMPTS = 20  # the player or the waveform pass may still hold the old file briefly
SWAP_WAIT_S = 0.15
_NUMBER = re.compile(r"^(.*) (\d{2,})$")


@dataclass(frozen=True)
class PlaybackEdit:
    """What the player changes about a voice: stretches it leaves out and its gain."""

    cuts: tuple[Span, ...] = ()
    gain: float = 1.0  # linear, 0–1

    @property
    def changes_nothing(self) -> bool:
        return not self.cuts and self.gain >= 0.999

    @property
    def saved_ms(self) -> int:
        return total_ms(self.cuts)


def numbered_name(name: str, taken: set[str]) -> str:
    """«stem 01.ext», or the next free number. A name that is already one of these numbered
    copies («stem 01», beside a «stem») counts on from its original's name instead of
    growing another number. `taken` holds the casefolded names already in use."""
    stem, suffix = Path(name).stem, Path(name).suffix
    stems = {Path(t).stem for t in taken}
    match = _NUMBER.match(stem)
    if match and match.group(1).casefold() in stems:
        stem = match.group(1)
    folder = voices_dir()
    n = 1
    while True:
        candidate = f"{stem} {n:02d}{suffix}"
        if candidate.casefold() not in taken and not (folder / candidate).exists():
            return candidate
        n += 1


def _shift_notes(notes: list[TimestampNote], cuts: tuple[Span, ...]) -> None:
    for note in notes:
        note.move_to(trimmed_ms(note.position_ms, cuts))


def _shift_segments(
    segments: list[TranscriptSegment], cuts: tuple[Span, ...]
) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(trimmed_ms(s.start_ms, cuts), trimmed_ms(s.end_ms, cuts), s.text)
        for s in segments
    ]


def _swap(new: Path, target: Path) -> None:
    """Move `new` over `target`. On Windows a file another process still has open cannot be
    replaced, so a player letting go of it a moment later is waited for."""
    for attempt in range(SWAP_ATTEMPTS):
        try:
            new.replace(target)
            return
        except PermissionError:
            if attempt == SWAP_ATTEMPTS - 1:
                new.unlink(missing_ok=True)
                raise
            time.sleep(SWAP_WAIT_S)


class VoiceRenderService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def _taken(self, but: int | None = None) -> set[str]:
        with UnitOfWork(self._sf) as uow:
            voices = uow.voices.list_all(include_trashed=True)
        return {name_key(v.file_path) for v in voices if v.id != but}

    def copy_name(self, voice_id: int) -> str:
        """The name a new copy of this voice would get."""
        with UnitOfWork(self._sf) as uow:
            source = Path(uow.voices.get(voice_id).file_path)
        return numbered_name(source.stem + output_suffix(source), self._taken())

    def save(
        self,
        voice_id: int,
        edit: PlaybackEdit,
        replace: bool,
        cancel: threading.Event | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Voice:
        """Blocking: decodes and encodes the whole file. Run it off the UI thread.

        Returns the new voice, or the replaced one."""
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
        source = Path(voice.file_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        suffix = output_suffix(source)
        if not replace:
            target = voices_dir() / self.copy_name(voice_id)
            render(source, target, edit.cuts, edit.gain, cancel, on_progress)
            try:
                return self._add_copy(voice, target, edit.cuts)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        if is_stored(source) and source.suffix.lower() == suffix:
            target = source  # the store's own copy: written over in place
        else:  # outside the store (a Bale voice, a restored file) or a new format: beside it
            target = voices_dir() / free_name(source.stem + suffix, self._taken(but=voice_id))
        fresh = target.with_name(f".{target.stem}.new{suffix}")
        render(source, fresh, edit.cuts, edit.gain, cancel, on_progress)
        _swap(fresh, target)
        replaced = self._replace_audio(voice_id, target, edit.cuts)
        if target != source:
            discard(source)  # only ever deletes the store's own copy
        return replaced

    def _add_copy(self, original: Voice, path: Path, cuts: tuple[Span, ...]) -> Voice:
        assert original.id is not None
        info = probe(path)
        with UnitOfWork(self._sf) as uow:
            copy = uow.voices.add(
                Voice(
                    file_path=str(path),
                    duration_ms=info.duration_ms,
                    format=info.format,
                    tag_ids=set(original.tag_ids),
                    imported_at=utcnow(),
                )
            )
            assert copy.id is not None
            notes = uow.timestamp_notes.list_for_voice(original.id)
            _shift_notes(notes, cuts)
            for note in notes:
                uow.timestamp_notes.add(
                    TimestampNote(copy.id, note.position_ms, note.text, note.created_at)
                )
            transcript = uow.transcripts.for_voice(original.id)
            if transcript is not None:
                uow.transcripts.add(
                    Transcript(
                        voice_id=copy.id,
                        segments=_shift_segments(transcript.segments, cuts),
                        language=transcript.language,
                        model=transcript.model,
                        created_at=transcript.created_at,
                    )
                )
        return copy

    def _replace_audio(self, voice_id: int, path: Path, cuts: tuple[Span, ...]) -> Voice:
        info = probe(path)
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            voice.file_path = str(path)
            voice.duration_ms = info.duration_ms
            voice.format = info.format
            saved = uow.voices.update(voice)
            notes = uow.timestamp_notes.list_for_voice(voice_id)
            _shift_notes(notes, cuts)
            for note in notes:
                uow.timestamp_notes.update(note)
            transcript = uow.transcripts.for_voice(voice_id)
            if transcript is not None:
                transcript.segments = _shift_segments(transcript.segments, cuts)
                uow.transcripts.update(transcript)
        return saved


def pause_cuts(path: Path, keep_ms: int) -> tuple[Span, ...]:
    """What the player would skip in `path` at this pause setting (reads the waveform,
    from its cache when the file has been opened before)."""
    waveform = extract(path, threading.Event())
    return cuts_for(find_pauses(waveform), keep_ms, waveform.duration_ms)


def trimmed_for_sending(path: Path, keep_ms: int, folder: Path) -> tuple[Path, tuple[Span, ...]]:
    """`path` with its pauses trimmed, written into `folder` under the same name — or
    `path` itself, with no cuts, when there is nothing to trim. Blocking."""
    cuts = pause_cuts(path, keep_ms)
    if not cuts:
        return path, ()
    target = folder / (path.stem + output_suffix(path))
    render(path, target, cuts)
    return target, cuts
