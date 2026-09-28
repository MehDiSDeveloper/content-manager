"""Searching the workspace from Bale: «؟», /search and the save question's «🔍 جستجو»."""

from pathlib import Path
from typing import Any

import pytest

from podcast_workspace.domain.entities import TimestampNote, Voice
from podcast_workspace.repositories.db import create_sqlite_engine, migrate
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.bale_bot import SAVE_SEARCH, _Worker
from podcast_workspace.services.bale_search import T_EXPIRED, T_NOTHING
from podcast_workspace.services.settings_service import BotOwner
from podcast_workspace.services.workspace import Workspace

OWNER = 7


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, dict[str, Any] | None]] = []
        self.edits: list[tuple[int, str, dict[str, Any] | None]] = []
        self.answers: list[str | None] = []
        self.files: list[tuple[str, Path | str, str | None]] = []

    def send_message(self, chat_id: int, text: str, markup: dict[str, Any] | None = None):
        self.sent.append((len(self.sent) + 1, text, markup))
        return {"message_id": len(self.sent)}

    def edit_message_text(self, chat_id, message_id, text, markup=None) -> None:
        self.edits.append((message_id, text, markup))

    def answer_callback_query(self, callback_id, text=None, show_alert=False) -> None:
        self.answers.append(text)

    def send_file(self, chat_id, field, file, caption=None) -> dict[str, Any]:
        self.files.append((field, file, caption))
        return {"message_id": 99, field: {"file_id": "bale-file-1"}}


@pytest.fixture
def ws(tmp_path):
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    migrate(engine)
    workspace = Workspace(engine)
    workspace.settings.set_bale_owner(BotOwner(OWNER, "me"))
    yield workspace
    engine.dispose()


@pytest.fixture
def bot(ws):
    client = FakeClient()
    worker = _Worker(ws.bot, client, lambda *_: None, lambda _: None)  # type: ignore[arg-type]
    return worker, client


def message(text: str) -> dict[str, Any]:
    return {"message": {"chat": {"id": OWNER, "type": "private"}, "text": text}}


def tap(message_id: int, data: str) -> dict[str, Any]:
    chat = {"id": OWNER, "type": "private"}
    return {
        "callback_query": {
            "id": "c",
            "data": data,
            "message": {"chat": chat, "message_id": message_id},
        }
    }


def buttons(markup: dict[str, Any] | None) -> dict[str, str]:
    return {b["text"]: b["callback_data"] for row in (markup or {})["inline_keyboard"] for b in row}


def idea(ws, text: str, *tags: str):
    tag_ids = {ws.tags.resolve_or_create(name).tag.id for name in tags}
    return ws.ideas.create(text, tag_ids)


def test_a_question_mark_searches_instead_of_asking_to_save(ws, bot):
    worker, client = bot
    idea(ws, "خواب و حافظه\nخواب کافی حافظه را قوی می‌کند")
    idea(ws, "ورزش صبحگاهی")
    worker._handle(message("؟ خواب"))
    _, text, markup = client.sent[-1]
    assert "خواب و حافظه" in text and "ورزش" not in text
    assert len(ws.ideas.list_all()) == 2  # nothing new was saved
    worker._handle(tap(1, buttons(markup)["۱"]))
    assert client.sent[-1][1].startswith("💡 خواب و حافظه\nخواب کافی")


def test_search_after_slash_search_then_back_to_ideas(ws, bot):
    worker, client = bot
    idea(ws, "خواب و حافظه")
    worker._handle(message("/search"))
    worker._handle(message("حافظه"))
    assert "خواب و حافظه" in client.sent[-1][1]
    worker._handle(message("یک ایدهٔ تازه"))
    assert "ذخیره شود؟" in client.sent[-1][1]  # one query only, then messages are ideas again


def test_the_save_question_can_search_that_text_instead(ws, bot):
    worker, client = bot
    idea(ws, "خواب و حافظه")
    worker._handle(message("حافظه"))
    question = client.sent[-1][0]
    sent_before = len(client.sent)
    worker._handle(tap(question, SAVE_SEARCH))
    assert len(ws.ideas.list_all()) == 1
    assert len(client.sent) == sent_before  # the question itself became the results
    assert client.edits[-1][0] == question and "خواب و حافظه" in client.edits[-1][1]


def test_a_hashtag_picks_the_nearest_tag_and_x_takes_it_away(ws, bot):
    worker, client = bot
    idea(ws, "یک", "روان شناسی")
    idea(ws, "دو")
    worker._handle(message("؟ #روانشناسی"))  # no space: still the same tag
    results, text, markup = client.sent[-1]
    assert "یک" in text and "دو" not in text
    worker._handle(tap(results, buttons(markup)["✖ روان شناسی"]))
    assert "کلمه‌ای بفرستید" in client.edits[-1][1]  # nothing left to search: the menu


def test_tags_narrow_the_results_in_place(ws, bot):
    worker, client = bot
    idea(ws, "خواب یک", "سلامت")
    idea(ws, "خواب دو")
    worker._handle(message("؟ خواب"))
    results, _, markup = client.sent[-1]
    worker._handle(tap(results, buttons(markup)["🏷 سلامت (۱)"]))
    assert "خواب یک" in client.edits[-1][1] and "خواب دو" not in client.edits[-1][1]


def test_pages_number_on_and_forget_after_a_restart(ws, bot):
    worker, client = bot
    for n in range(7):
        idea(ws, f"خواب {n}")
    worker._handle(message("؟ خواب"))
    results, _, markup = client.sent[-1]
    worker._handle(tap(results, buttons(markup)["بعدی"]))
    assert "۶." in client.edits[-1][1] and "۱." not in client.edits[-1][1]
    fresh = _Worker(ws.bot, client, lambda *_: None, lambda _: None)  # type: ignore[arg-type]
    fresh._handle(tap(results, buttons(markup)["بعدی"]))
    assert client.answers[-1] == T_EXPIRED


def test_nothing_found_says_so(ws, bot):
    worker, client = bot
    worker._handle(message("؟ هیچ"))
    assert T_NOTHING in client.sent[-1][1]


def test_a_voice_is_found_by_its_notes_and_sent_as_audio_once(ws, bot, tmp_path):
    worker, client = bot
    audio = tmp_path / "take.ogg"
    audio.write_bytes(b"OggS")
    with UnitOfWork(ws.voices._sf) as uow:
        voice = uow.voices.add(Voice(file_path=str(audio), duration_ms=65_000))
        uow.timestamp_notes.add(TimestampNote(voice.id, 0, "دربارهٔ خواب"))
    idea(ws, "خواب شبانه")  # named, so listed first
    worker._handle(message("؟ خواب"))
    _, text, markup = client.sent[-1]
    assert "۲. 🎙 take.ogg · ۱:۰۵" in text and "«دربارهٔ خواب»" in text
    worker._handle(tap(1, buttons(markup)["۲"]))
    worker._handle(tap(1, buttons(markup)["۲"]))
    assert [(f, str(p)) for f, p, _ in client.files] == [
        ("voice", str(audio)),
        ("voice", "bale-file-1"),  # the second time Bale already has it
    ]
