"""From ideas to episodes: adding them, starting an episode from them, and undoing both."""

import pytest

from podcast_workspace.domain.entities import Voice
from podcast_workspace.domain.smart_links import LinkKind
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.history import ChangeKind
from podcast_workspace.services.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def _voice(ws: Workspace, name: str = "مصاحبه-اول.mp3") -> int:
    with UnitOfWork(ws.episodes._sf) as uow:
        return uow.voices.add(Voice(file_path=name)).id


def test_several_ideas_go_into_an_episode_as_one_undo_step(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    idea = ws.ideas.create("کتاب‌فروشی‌های انقلاب")
    voice = _voice(ws)
    items = [(LinkKind.IDEA, idea.id), (LinkKind.VOICE, voice)]

    ws.episodes.set_linked(episode.id, items, True)
    saved = ws.episodes.get(episode.id)
    assert saved.idea_note_ids == {idea.id} and saved.voice_ids == {voice}
    assert ws.episodes.link_counts() == {(LinkKind.IDEA, idea.id): 1, (LinkKind.VOICE, voice): 1}
    assert [e.id for e in ws.episodes.episodes_with(LinkKind.IDEA, idea.id)] == [episode.id]

    change = ws.history.undo()
    assert change.kind is ChangeKind.LINKED and len(change.details) == 2  # both named
    emptied = ws.episodes.get(episode.id)
    assert emptied.idea_note_ids == set() and emptied.voice_ids == set()


def test_adding_what_is_already_there_records_nothing(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    idea = ws.ideas.create("ایده")
    ws.episodes.set_linked(episode.id, [(LinkKind.IDEA, idea.id)], True)
    top = ws.history.peek_undo()
    ws.episodes.set_linked(episode.id, [(LinkKind.IDEA, idea.id)], True)
    assert ws.history.peek_undo() is top


def test_a_new_episode_starts_from_the_ideas_names_and_tags(ws) -> None:
    city = ws.tags.create("شهر", allow_similar=True)
    radio = ws.tags.create("رادیو", allow_similar=True)
    idea = ws.ideas.create("کتاب‌فروش پیر\nکه پنجاه سال است آنجاست", [city.id])
    voice = _voice(ws, "روایت-رادیو.mp3")
    ws.voices.set_tags(voice, [radio.id])

    episode = ws.episodes.create_from([(LinkKind.IDEA, idea.id), (LinkKind.VOICE, voice)])
    assert episode.title == "کتاب‌فروش پیر"  # the first idea's first line
    assert episode.tag_ids == {city.id, radio.id}
    assert episode.idea_note_ids == {idea.id} and episode.voice_ids == {voice}

    assert ws.episodes.create_from([(LinkKind.VOICE, voice)]).title == "روایت-رادیو"


def test_undoing_a_new_episode_takes_it_and_its_links_away(ws) -> None:
    idea = ws.ideas.create("ایده")
    episode = ws.episodes.create_from([(LinkKind.IDEA, idea.id)])
    ws.history.undo()
    assert ws.episodes.list_all() == []
    assert ws.episodes.link_counts() == {}
    ws.history.redo()
    assert ws.episodes.get(episode.id).idea_note_ids == {idea.id}
