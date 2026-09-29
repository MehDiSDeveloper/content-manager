"""A season's brief: stored, one undo step per writing run, and carried by exports."""

import pytest

from podcast_workspace.services.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def test_a_new_season_starts_with_an_empty_brief(ws) -> None:
    season = ws.seasons.get(ws.seasons.create("فصل ۱").id)
    assert (season.summary, season.outline) == ("", "")


def test_writing_the_brief_is_stored_and_one_undo_step(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    for summary in ("د", "دربارهٔ", "دربارهٔ اعتماد"):
        ws.seasons.write_brief(season.id, summary, "۱. شروع")
    stored = ws.seasons.get(season.id)
    assert (stored.summary, stored.outline) == ("دربارهٔ اعتماد", "۱. شروع")

    ws.history.undo()
    stored = ws.seasons.get(season.id)
    assert (stored.summary, stored.outline) == ("", "")
    ws.history.redo()
    assert ws.seasons.get(season.id).summary == "دربارهٔ اعتماد"


def test_an_unchanged_brief_records_nothing(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "")
    ws.history.undo()  # the writing run
    ws.history.redo()
    ws.seasons.write_brief(season.id, "هدف", "")
    ws.history.undo()
    assert ws.seasons.get(season.id).summary == ""


def test_renaming_keeps_the_brief(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    ws.seasons.rename(season.id, "فصل یکم")
    stored = ws.seasons.get(season.id)
    assert (stored.title, stored.summary, stored.outline) == ("فصل یکم", "هدف", "ساختار")


def test_undoing_a_delete_brings_the_brief_back(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    ws.seasons.delete(season.id)
    ws.history.undo()
    (restored,) = ws.seasons.list_all()
    assert (restored.summary, restored.outline) == ("هدف", "ساختار")


def test_the_brief_survives_an_export_and_restore(ws, tmp_path) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    target = tmp_path / "backup.zip"
    ws.backup.export(target)
    ws.seasons.write_brief(season.id, "", "")

    ws.backup.restore(target)
    stored = ws.seasons.get(season.id)
    assert (stored.summary, stored.outline) == ("هدف", "ساختار")
