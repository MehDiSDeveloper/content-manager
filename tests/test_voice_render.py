"""Saving a voice as it plays (pauses trimmed, volume applied), and the Bale bot sending
voices trimmed the same way."""

import math
import os
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from podcast_workspace.audio.ffmpeg import probe_stream
from podcast_workspace.audio.render import output_suffix, render, trimmed_ms
from podcast_workspace.domain.entities import Transcript, TranscriptSegment
from podcast_workspace.paths import voices_dir
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.bale_bot import _Worker
from podcast_workspace.services.bale_search import _clock
from podcast_workspace.services.settings_service import BotOwner
from podcast_workspace.services.voice_render import PlaybackEdit, numbered_name, pause_cuts
from podcast_workspace.services.workspace import Workspace

RATE = 16000
OWNER = 7


def _speech_wav(path: Path, pattern: list[tuple[str, float]]) -> Path:
    """Tone for «talk», near-silence for «pause», in the given order."""
    parts = []
    for kind, seconds in pattern:
        t = np.arange(int(RATE * seconds)) / RATE
        if kind == "talk":
            parts.append(0.5 * np.sin(2 * math.pi * 220 * t))
        else:
            parts.append(0.0005 * np.sin(2 * math.pi * 50 * t))
    samples = (np.concatenate(parts) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return path


def _peak(path: Path) -> float:
    with wave.open(str(path), "rb") as src:
        data = np.frombuffer(src.readframes(src.getnframes()), "<i2")
    return float(np.abs(data).max()) / 32767


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(home))
    return home


@pytest.fixture
def ws(home):
    workspace = Workspace.open(home / "w.db")
    yield workspace
    workspace.close()


@pytest.fixture
def recorder(tmp_path) -> Path:
    folder = tmp_path / "recorder"
    folder.mkdir()
    return folder


# the pure parts ------------------------------------------------------------------------
def test_a_time_moves_back_by_the_cuts_before_it():
    cuts = ((1000, 3000), (5000, 6000))
    assert trimmed_ms(500, cuts) == 500
    assert trimmed_ms(2000, cuts) == 1000  # inside a cut: where the cut was
    assert trimmed_ms(4000, cuts) == 2000
    assert trimmed_ms(7000, cuts) == 4000


def test_copies_are_numbered_and_a_copy_of_a_copy_counts_on():
    taken = {"take.wav", "track 12.mp3"}
    assert numbered_name("take.wav", taken) == "take 01.wav"
    assert numbered_name("take.wav", taken | {"take 01.wav"}) == "take 02.wav"
    assert numbered_name("take 01.wav", taken | {"take 01.wav"}) == "take 02.wav"
    # «12» is part of this name, not a copy's number: there is no «track» it was copied from
    assert numbered_name("track 12.mp3", taken) == "track 12 01.mp3"


def test_formats_without_an_encoder_come_out_as_m4a():
    assert output_suffix(Path("a.MP3")) == ".mp3"
    assert output_suffix(Path("a.amr")) == ".m4a"


def test_render_leaves_the_cuts_out_and_scales(tmp_path):
    source = _speech_wav(tmp_path / "a.wav", [("talk", 1), ("pause", 2), ("talk", 1)])
    target = tmp_path / "b.wav"
    render(source, target, ((1200, 2800),), gain=0.5)
    assert abs(probe_stream(target).duration_ms - 2400) <= 20
    assert _peak(target) == pytest.approx(0.25, abs=0.02)
    assert not list(tmp_path.glob(".*partial*"))


# saving from the player ----------------------------------------------------------------
def _voice_with_notes(ws, recorder):
    ws.source.set_folder(recorder)
    take = _speech_wav(recorder / "take.wav", [("talk", 1), ("pause", 3), ("talk", 1)])
    recorded = time.time() - 600
    os.utime(take, (recorded, recorded))
    voice = ws.source.add(take)
    tag = ws.tags.resolve_or_create("سلامت").tag
    ws.voices.set_tags(voice.id, {tag.id})
    ws.timestamp_notes.add(voice.id, 4500, "بعد از مکث")
    with UnitOfWork(ws.voices._sf) as uow:
        uow.transcripts.replace(
            Transcript(
                voice.id, [TranscriptSegment(0, 1000, "یک"), TranscriptSegment(4000, 5000, "دو")]
            )
        )
    cuts = pause_cuts(Path(voice.file_path), 500)
    assert cuts and 2000 <= sum(b - a for a, b in cuts) <= 2600
    return ws.voices.get(voice.id), PlaybackEdit(cuts, 0.5), tag


def test_a_new_copy_carries_tags_notes_and_transcript_at_the_new_times(ws, recorder):
    voice, edit, tag = _voice_with_notes(ws, recorder)
    copy = ws.voice_render.save(voice.id, edit, replace=False)

    assert copy.id != voice.id and Path(copy.file_path).name == "take 01.wav"
    assert Path(copy.file_path).parent == voices_dir()
    assert copy.tag_ids == {tag.id}
    assert abs(copy.duration_ms - (5000 - edit.saved_ms)) <= 30
    [note] = ws.timestamp_notes.list_for_voice(copy.id)
    assert note.position_ms == 4500 - edit.saved_ms
    segments = ws.transcripts.get(copy.id).segments
    assert [(s.start_ms, s.text) for s in segments] == [(0, "یک"), (4000 - edit.saved_ms, "دو")]
    # the original is as it was
    assert ws.voices.get(voice.id).file_path == voice.file_path
    assert ws.timestamp_notes.list_for_voice(voice.id)[0].position_ms == 4500
    assert ws.voice_render.copy_name(voice.id) == "take 02.wav"


def test_replacing_keeps_the_voice_and_moves_its_times(ws, recorder):
    voice, edit, _ = _voice_with_notes(ws, recorder)
    saved = ws.voice_render.save(voice.id, edit, replace=True)

    assert saved.id == voice.id and saved.file_path == voice.file_path
    assert abs(saved.duration_ms - (5000 - edit.saved_ms)) <= 30
    assert _peak(Path(saved.file_path)) < 0.3
    assert ws.timestamp_notes.list_for_voice(voice.id)[0].position_ms == 4500 - edit.saved_ms
    assert ws.transcripts.get(voice.id).segments[1].start_ms == 4000 - edit.saved_ms
    assert len(ws.voices.list_all()) == 1
    # the recording it came from is still known: not offered again by the audio folder
    assert ws.source.pending() == []


def test_nothing_to_apply():
    assert PlaybackEdit((), 1.0).changes_nothing
    assert not PlaybackEdit((), 0.5).changes_nothing


# the Bale bot ------------------------------------------------------------------------------
class FakeClient:
    def __init__(self) -> None:
        self.files: list[tuple[str, str, str | None, int]] = []
        self.sent: list[str] = []

    def send_message(self, chat_id, text, markup=None):
        self.sent.append(text)
        return {"message_id": len(self.sent)}

    def edit_message_text(self, chat_id, message_id, text, markup=None) -> None:
        pass

    def answer_callback_query(self, callback_id, text=None, show_alert=False) -> None:
        pass

    def send_file(self, chat_id, field, file, caption=None):
        length = probe_stream(file).duration_ms if isinstance(file, Path) else -1
        self.files.append((field, str(file), caption, length))
        return {"message_id": 99, field: {"file_id": "bale-file-1"}}


def test_the_bot_sends_a_voice_with_its_pauses_trimmed(ws, recorder):
    ws.settings.set_bale_owner(BotOwner(OWNER, "me"))
    ws.settings.set_silence_keep_ms(500)
    voice, edit, _ = _voice_with_notes(ws, recorder)
    client = FakeClient()
    worker = _Worker(ws.bot, client, lambda *_: None, lambda _: None)  # type: ignore[arg-type]
    chat = {"id": OWNER, "type": "private"}
    worker._handle({"message": {"chat": chat, "text": "؟ take"}})
    tap = {
        "callback_query": {
            "id": "c",
            "data": f"s|o|v|{voice.id}",
            "message": {"chat": chat, "message_id": 1},
        }
    }
    worker._handle(tap)
    worker._handle(tap)

    (field, _, caption, length), (_, again, _, _) = client.files
    assert field == "document"  # a wav goes as a file, as before
    assert abs(length - (5000 - edit.saved_ms)) <= 30
    assert "✂️" in caption
    assert f"{_clock(4500 - edit.saved_ms)} بعد از مکث" in caption
    assert again == "bale-file-1"  # the trimmed upload is reused
