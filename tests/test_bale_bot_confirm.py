"""Nothing from Bale enters the workspace until the owner says yes."""

from typing import Any

import pytest

from podcast_workspace.repositories.db import create_sqlite_engine, migrate
from podcast_workspace.services.bale_bot import (
    SAVE_NO,
    SAVE_YES,
    T_ASK_EXPIRED,
    ItemKind,
    ItemRef,
    _Worker,
)
from podcast_workspace.services.settings_service import BotOwner
from podcast_workspace.services.workspace import Workspace

OWNER = 7


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, dict[str, Any] | None]] = []
        self.edits: list[tuple[int, str, dict[str, Any] | None]] = []
        self.answers: list[str | None] = []

    def send_message(self, chat_id: int, text: str, markup: dict[str, Any] | None = None):
        self.sent.append((len(self.sent) + 1, text, markup))
        return {"message_id": len(self.sent)}

    def edit_message_text(self, chat_id, message_id, text, markup=None) -> None:
        self.edits.append((message_id, text, markup))

    def answer_callback_query(self, callback_id, text=None, show_alert=False) -> None:
        self.answers.append(text)


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
    delivered: list[ItemRef] = []
    worker = _Worker(ws.bot, client, lambda *_: None, delivered.append)  # type: ignore[arg-type]
    return worker, client, delivered


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


def test_a_text_idea_waits_for_an_answer(ws, bot):
    worker, client, delivered = bot
    worker._handle(message("ایده‌ای دربارهٔ خواب #سلامت"))
    assert ws.ideas.list_all() == []
    assert ws.tags.list_all() == []
    assert delivered == []
    assert "ایده‌ای دربارهٔ خواب" in client.sent[-1][1]


def test_no_leaves_no_trace(ws, bot):
    worker, client, delivered = bot
    worker._handle(message("ایده‌ای دربارهٔ خواب #سلامت"))
    question = client.sent[-1][0]
    worker._handle(tap(question, SAVE_NO))
    assert ws.ideas.list_all() == []
    assert ws.tags.list_all() == []  # the hashtag did not create a tag either
    assert delivered == []
    assert client.edits[-1][0] == question and client.edits[-1][2] is None


def test_yes_saves_it_and_turns_the_question_into_the_tag_keyboard(ws, bot):
    worker, client, delivered = bot
    worker._handle(message("ایده‌ای دربارهٔ خواب #سلامت"))
    question = client.sent[-1][0]
    sent_before = len(client.sent)
    worker._handle(tap(question, SAVE_YES))
    [idea] = ws.ideas.list_all()
    assert idea.text == "ایده‌ای دربارهٔ خواب"
    assert [t.name for t in ws.tags.by_ids(idea.tag_ids)] == ["سلامت"]
    assert delivered == [ItemRef(ItemKind.IDEA, idea.id)]
    assert len(client.sent) == sent_before  # edited in place, no extra message
    assert client.edits[-1][0] == question and client.edits[-1][2]["inline_keyboard"]


def test_a_second_tap_saves_nothing_more(ws, bot):
    worker, client, _ = bot
    worker._handle(message("یک ایده"))
    question = client.sent[-1][0]
    worker._handle(tap(question, SAVE_YES))
    worker._handle(tap(question, SAVE_YES))
    assert len(ws.ideas.list_all()) == 1
    assert client.answers[-1] is None


def test_a_question_from_before_a_restart_says_so(ws, bot):
    worker, client, _ = bot
    worker._handle(tap(99, SAVE_YES))
    assert ws.ideas.list_all() == []
    assert client.answers[-1] == T_ASK_EXPIRED


def test_hashtags_alone_still_tag_the_last_saved_item_without_asking(ws, bot):
    worker, client, _ = bot
    worker._handle(message("یک ایده"))
    worker._handle(tap(client.sent[-1][0], SAVE_YES))
    worker._handle(message("#خواب"))
    [idea] = ws.ideas.list_all()
    assert [t.name for t in ws.tags.by_ids(idea.tag_ids)] == ["خواب"]
