"""The script brief: its defaults, that it is stored, undone and exported, and the prompt."""

import pytest

from podcast_workspace.domain.script_brief import Approach, Mood, Register, ScriptBrief
from podcast_workspace.services.workspace import Workspace


def test_defaults_lean_on_the_conceptual_approach_only() -> None:
    brief = ScriptBrief()
    assert brief.approaches == {Approach.CONCEPTUAL}
    assert brief.moods == frozenset()


def test_json_round_trip_drops_what_it_does_not_know() -> None:
    brief = ScriptBrief(about="دربارهٔ زمان", moods=frozenset({Mood.CALM}), depth=4)
    assert ScriptBrief.from_dict(brief.to_dict()) == brief
    data = brief.to_dict() | {"moods": ["calm", "future"], "register": "?", "depth": 9}
    loaded = ScriptBrief.from_dict(data)
    assert loaded.moods == {Mood.CALM}
    assert loaded.register is Register.SEMI_FORMAL
    assert loaded.depth == 5
    assert ScriptBrief.from_dict({}) == ScriptBrief()


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def test_a_run_of_edits_is_one_undo_step(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    before = ws.episodes.get(episode.id).updated_at
    for about in ("د", "دربارهٔ", "دربارهٔ زمان"):
        ws.episodes.set_brief(episode.id, ScriptBrief(about=about, depth=3))
    assert ws.episodes.get(episode.id).brief.about == "دربارهٔ زمان"

    ws.history.undo()
    restored = ws.episodes.get(episode.id)
    assert restored.brief == ScriptBrief()
    assert restored.updated_at == before


def test_editing_the_title_keeps_the_brief(ws) -> None:
    episode = ws.episodes.create("قسمت اول")
    ws.episodes.set_brief(episode.id, ScriptBrief(depth=2))
    saved = ws.episodes.update(episode.id, title="قسمت یکم", status=episode.status, next_action="")
    assert saved.brief.depth == 2


def test_the_brief_survives_an_export_and_restore(ws, tmp_path) -> None:
    episode = ws.episodes.create("قسمت اول")
    brief = ScriptBrief(about="زمان", moods=frozenset({Mood.HUMOROUS}), minutes=25)
    ws.episodes.set_brief(episode.id, brief)
    archive = tmp_path / "export.zip"
    ws.backup.export(archive)
    ws.episodes.set_brief(episode.id, ScriptBrief())
    ws.backup.restore(archive)
    assert ws.episodes.get(episode.id).brief == brief
