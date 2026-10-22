"""A voice from Bale is asked for a name: typed, or said in a short voice."""

import wave
from pathlib import Path
from typing import Any

import pytest

from podcast_workspace.repositories.db import create_sqlite_engine, migrate
from podcast_workspace.services.bale_bot import (
    MAX_NAME_CHARS,
    SAVE_YES,
    T_NAME_NO_MODEL,
    T_NAME_TOO_LONG,
    T_NAME_UNHEARD,
    _Worker,
)
from podcast_workspace.services.settings_service import BotOwner
from podcast_workspace.services.workspace import Workspace

OWNER = 7


def _wav(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\0\0" * int(8000 * seconds))


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, dict[str, Any] | None]] = []
        self.edits: list[tuple[int, str, dict[str, Any] | None]] = []

    def send_message(self, chat_id: int, text: str, markup: dict[str, Any] | None = None):
        self.sent.append((len(self.sent) + 1, text, markup))
        return {"message_id": len(self.sent)}

    def edit_message_text(self, chat_id, message_id, text, markup=None) -> None:
        self.edits.append((message_id, text, markup))

    def answer_callback_query(self, callback_id, text=None, show_alert=False) -> None:
        pass

    def get_file(self, file_id: str) -> dict[str, Any]:
        return {"file_path": f"{file_id}.wav"}

    def download(self, file_path: str, target: Path) -> None:
        _wav(target)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path / "home"))
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    migrate(engine)
    workspace = Workspace(engine)
    workspace.settings.set_bale_owner(BotOwner(OWNER, "me"))
    yield workspace
    engine.dispose()


@pytest.fixture
def bot(ws):
    client = FakeClient()
    worker = _Worker(ws.bot, client, lambda *_: None, lambda _ref: None)  # type: ignore[arg-type]
    return worker, client


CHAT = {"id": OWNER, "type": "private"}


def voice(file_id: str = "v", seconds: int = 40) -> dict[str, Any]:
    return {"message": {"chat": CHAT, "voice": {"file_id": file_id, "duration": seconds}}}


def text(body: str) -> dict[str, Any]:
    return {"message": {"chat": CHAT, "text": body}}


def hear(ws, monkeypatch, said: str) -> None:
    monkeypatch.setattr(ws.transcripts, "can_transcribe", lambda: True)
    monkeypatch.setattr(ws.transcripts, "transcribe_clip", lambda _path: said)


def test_a_typed_name_saves_the_voice_under_it_with_its_hashtags(ws, bot):
    worker, client = bot
    worker._handle(voice())
    assert ws.voices.list_all() == []  # still asking
    worker._handle(text("مصاحبه با علی #گفتگو"))
    [saved] = ws.voices.list_all()
    assert Path(saved.file_path).stem == "مصاحبه با علی"
    assert [t.name for t in ws.tags.by_ids(saved.tag_ids)] == ["گفتگو"]
    assert client.edits[-1][2]["inline_keyboard"]  # the question became the tag keyboard


def test_a_short_spoken_name_is_transcribed_and_leaves_no_clip(ws, bot, monkeypatch):
    worker, _ = bot
    hear(ws, monkeypatch, " ایدهٔ خواب. ")
    worker._handle(voice("idea"))
    worker._handle(voice("name", seconds=4))
    [saved] = ws.voices.list_all()
    assert Path(saved.file_path).stem == "ایدهٔ خواب"
    assert [p.name for p in Path(saved.file_path).parent.iterdir()] == ["ایدهٔ خواب.wav"]


def test_a_long_name_voice_is_refused_and_the_question_still_waits(ws, bot, monkeypatch):
    worker, client = bot
    hear(ws, monkeypatch, "نام")
    worker._handle(voice("idea"))
    worker._handle(voice("long", seconds=16))
    assert client.sent[-1][1] == T_NAME_TOO_LONG
    assert ws.voices.list_all() == []
    worker._handle(voice("short", seconds=3))
    [saved] = ws.voices.list_all()
    assert Path(saved.file_path).stem == "نام"


def test_a_spoken_name_needs_the_model(ws, bot, monkeypatch):
    worker, client = bot
    monkeypatch.setattr(ws.transcripts, "can_transcribe", lambda: False)
    worker._handle(voice("idea"))
    worker._handle(voice("name", seconds=3))
    assert client.sent[-1][1] == T_NAME_NO_MODEL
    assert ws.voices.list_all() == []


def test_nothing_heard_asks_again(ws, bot, monkeypatch):
    worker, client = bot
    hear(ws, monkeypatch, "")
    worker._handle(voice("idea"))
    question = client.sent[-1][0]
    worker._handle(voice("name", seconds=3))
    assert client.sent[-1][1] == T_NAME_UNHEARD
    assert client.edits[-1][0] == question and client.edits[-1][2]["inline_keyboard"]


def test_a_long_name_is_cut_to_fit(ws, bot, monkeypatch):
    worker, _ = bot
    hear(ws, monkeypatch, "کلمه " * 80)
    worker._handle(voice("idea"))
    worker._handle(voice("name", seconds=14))
    [saved] = ws.voices.list_all()
    stem = Path(saved.file_path).stem
    assert len(stem) <= MAX_NAME_CHARS and stem.startswith("کلمه کلمه")


def test_the_button_still_saves_it_unnamed_and_ends_the_wait(ws, bot):
    worker, client = bot
    worker._handle(voice())
    question = client.sent[-1][0]
    worker._handle(
        {
            "callback_query": {
                "id": "c",
                "data": SAVE_YES,
                "message": {"chat": CHAT, "message_id": question},
            }
        }
    )
    assert len(ws.voices.list_all()) == 1
    worker._handle(text("یک ایدهٔ متنی"))  # a plain idea again, not a name
    assert ws.ideas.list_all() == [] and "ایدهٔ متنی ذخیره شود" in client.sent[-1][1]


def test_the_same_name_twice_gets_a_number(ws, bot):
    worker, _ = bot
    for file_id in ("a", "b"):
        worker._handle(voice(file_id))
        worker._handle(text("تکرار"))
    names = sorted(Path(v.file_path).stem for v in ws.voices.list_all())
    assert names == ["تکرار", "تکرار 02"]
