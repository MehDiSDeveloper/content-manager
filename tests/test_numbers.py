"""Seasons and episodes keep the order their numbers give, whenever they were made."""

import pytest

from podcast_workspace.services.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def test_an_episode_made_early_takes_its_place_in_the_prompt(ws) -> None:
    season = ws.seasons.create("فصل")
    third = ws.episodes.create("سوم", season.id)
    first = ws.episodes.create("اول", season.id)
    second = ws.episodes.create("دوم", season.id)
    ws.episodes.set_number(third.id, 3)
    ws.episodes.set_number(first.id, 1)

    # Numbered first, then the unnumbered as they were made.
    run = ws.script_prompt.material(third.id).season
    assert [e.title for e in run.before] == ["اول"]
    assert [e.title for e in run.after] == ["دوم"]
    ws.episodes.set_number(second.id, 2)
    assert [e.title for e in ws.script_prompt.material(third.id).season.before] == ["اول", "دوم"]


def test_seasons_list_by_number_and_undo_takes_it_back(ws) -> None:
    later = ws.seasons.create("دوم")
    ws.seasons.create("اول")
    ws.seasons.set_number(later.id, 2)
    assert [s.title for s in ws.seasons.list_all()] == ["دوم", "اول"]
    ws.history.undo()
    assert ws.seasons.get(later.id).number is None
