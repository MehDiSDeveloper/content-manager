"""The publish checklist: what counts as done, that it is stored, undone and exported."""

import pytest

from podcast_workspace.domain.publish import PublishChecklist, PublishStep
from podcast_workspace.services.workspace import Workspace


def test_where_counts_as_the_fifth_step_once_it_names_a_place() -> None:
    checklist = PublishChecklist().with_step(PublishStep.TITLE, True)
    assert (checklist.completed, checklist.total) == (1, 5)
    assert checklist.with_where("   \n  ").completed == 1  # blank lines name nowhere
    done = PublishChecklist(frozenset(PublishStep), "Castbox")
    assert done.is_complete


def test_places_are_kept_one_per_line_without_the_blanks() -> None:
    assert PublishChecklist(where="  Castbox \n\n  https://x.test/1  ").where == (
        "Castbox\nhttps://x.test/1"
    )


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def test_a_tick_is_stored_and_one_undo_takes_it_back(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    before = ws.episodes.get(episode.id).updated_at
    ws.episodes.check_publish_step(episode.id, PublishStep.COVER, True)
    assert ws.episodes.get(episode.id).publish.done == {PublishStep.COVER}

    ws.history.undo()
    restored = ws.episodes.get(episode.id)
    assert restored.publish == PublishChecklist()
    assert restored.updated_at == before  # an undone tick must not look like work


def test_typing_where_it_went_is_one_undo_step(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    for text in ("C", "Cast", "Castbox"):
        ws.episodes.set_published_where(episode.id, text)
    assert ws.episodes.get(episode.id).publish.where == "Castbox"
    ws.history.undo()
    assert ws.episodes.get(episode.id).publish.where == ""


def test_editing_the_title_keeps_the_checklist(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    ws.episodes.check_publish_step(episode.id, PublishStep.TITLE, True)
    saved = ws.episodes.update(episode.id, title="قسمت یکم", status=episode.status, next_action="")
    assert saved.publish.done == {PublishStep.TITLE}


def test_the_checklist_survives_an_export_and_restore(ws, tmp_path) -> None:
    episode = ws.episodes.create("قسمت اول")
    ws.episodes.check_publish_step(episode.id, PublishStep.CLIPS, True)
    ws.episodes.set_published_where(episode.id, "Castbox")
    target = tmp_path / "backup.zip"
    ws.backup.export(target)
    ws.episodes.check_publish_step(episode.id, PublishStep.CLIPS, False)

    ws.backup.restore(target)
    assert ws.episodes.get(episode.id).publish == PublishChecklist(
        frozenset({PublishStep.CLIPS}), "Castbox"
    )
