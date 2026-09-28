"""Added audio is kept in the workspace's own store; names that clash are asked about."""

import os
import wave
from pathlib import Path

import pytest

from podcast_workspace.domain.entities import Transcript, Voice
from podcast_workspace.domain.lifecycle import TrashKind
from podcast_workspace.paths import voices_dir
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.voice_store import NameChoice
from podcast_workspace.services.workspace import Workspace


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


def _wav(path: Path, seconds: float = 1.0, mtime: float | None = None) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\0\0" * int(8000 * seconds))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_an_added_file_is_copied_and_survives_the_folder_being_cleared(ws, recorder) -> None:
    ws.source.set_folder(recorder)
    take = _wav(recorder / "take.wav")
    assert [f.name for f in ws.source.pending()] == ["take.wav"]

    voice = ws.source.add(take)
    stored = Path(voice.file_path)
    assert stored.parent == voices_dir() and stored.is_file()
    assert voice.source_path == str(take.resolve())
    assert voice.duration_ms == 1000
    assert ws.source.pending() == []  # the original is not offered again

    take.unlink()
    assert Path(ws.voices.get(voice.id).file_path).is_file()


def test_a_new_take_under_a_reused_name_is_offered_again(ws, recorder) -> None:
    ws.source.set_folder(recorder)
    ws.source.add(_wav(recorder / "take.wav", 1.0, mtime=1_700_000_000))
    _wav(recorder / "take.wav", 2.0, mtime=1_700_000_500)  # the recorder starts over
    assert [f.name for f in ws.source.pending()] == ["take.wav"]


def test_a_namesake_comes_in_numbered_unless_told_otherwise(ws, tmp_path) -> None:
    first = ws.voices.import_files([_wav(tmp_path / "a.wav")]).imported[0]
    other = tmp_path / "other"
    other.mkdir()
    second = _wav(other / "A.WAV", 2.0)

    conflicts = ws.voices.name_conflicts([second])
    assert list(conflicts) == [second.resolve()] and conflicts[second.resolve()].id == first.id
    report = ws.voices.import_files([second])  # nobody asked: never overwritten
    assert Path(report.imported[0].file_path).name == "A (2).WAV"
    assert Path(ws.voices.get(first.id).file_path).name == "a.wav"


def test_skipping_a_namesake_brings_nothing_in(ws, tmp_path) -> None:
    ws.voices.import_files([_wav(tmp_path / "a.wav")])
    other = tmp_path / "other"
    other.mkdir()
    second = _wav(other / "a.wav", 2.0)
    report = ws.voices.import_files([second], {second.resolve(): NameChoice.SKIP})
    assert report.skipped == [second.resolve()] and report.imported == []
    assert len(ws.voices.list_all()) == 1


def test_replacing_keeps_the_voice_and_drops_its_transcript(ws, tmp_path) -> None:
    first = ws.voices.import_files([_wav(tmp_path / "a.wav", 1.0)]).imported[0]
    tag = ws.tags.create("سفر", allow_similar=True)
    ws.voices.set_tags(first.id, [tag.id])
    with UnitOfWork(ws.voices._sf) as uow:
        uow.transcripts.add(Transcript(voice_id=first.id, segments=[]))
    other = tmp_path / "other"
    other.mkdir()
    second = _wav(other / "a.wav", 3.0)

    report = ws.voices.import_files([second], {second.resolve(): NameChoice.REPLACE})
    replaced = report.imported[0]
    assert replaced.id == first.id and replaced.file_path == first.file_path
    assert replaced.duration_ms == 3000 and replaced.tag_ids == {tag.id}
    assert replaced.source_path == str(second.resolve())
    assert ws.transcripts.get(first.id) is None
    assert len(ws.voices.list_all()) == 1


def test_older_voices_are_copied_into_the_store(ws, tmp_path) -> None:
    outside = _wav(tmp_path / "old.wav")
    with UnitOfWork(ws.voices._sf) as uow:
        voice = uow.voices.add(Voice(file_path=str(outside.resolve())))
    assert ws.voices.secure_external() == 1
    moved = ws.voices.get(voice.id)
    assert Path(moved.file_path).parent == voices_dir()
    assert moved.source_path == str(outside.resolve())
    assert outside.is_file()  # the original is left alone
    assert ws.voices.secure_external() == 0


def test_purging_a_voice_deletes_only_the_stored_copy(ws, tmp_path) -> None:
    original = _wav(tmp_path / "a.wav")
    voice = ws.voices.import_files([original]).imported[0]
    ws.voices.delete(voice.id)
    ws.trash.purge([(TrashKind.VOICE, voice.id)])
    assert not Path(voice.file_path).exists()
    assert original.is_file()
