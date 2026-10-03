"""The script brief: its defaults, that it is stored, undone and exported, and the prompt."""

from dataclasses import replace

import pytest

from podcast_workspace.domain.script_brief import (
    Approach,
    Mood,
    NarrativeStyle,
    Register,
    ScriptBrief,
    ScriptFormat,
)
from podcast_workspace.domain.script_prompt import ScriptMaterial, build_prompt
from podcast_workspace.domain.smart_links import LinkKind
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


def test_a_brief_saved_with_one_formats_list_is_split_into_format_and_style() -> None:
    loaded = ScriptBrief.from_dict({"formats": ["dialogue", "recital", "story"]})
    assert loaded.format is ScriptFormat.DIALOGUE
    assert loaded.styles == {NarrativeStyle.RECITAL, NarrativeStyle.STORY}
    assert ScriptBrief.from_dict({"formats": ["story"]}).format is ScriptFormat.MONOLOGUE


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


def test_the_prompt_carries_the_episode_and_asks_before_writing(ws) -> None:
    season = ws.seasons.create("فصل زمان")
    ws.seasons.write_brief(season.id, "زمان از نگاه فیزیک و فلسفه", "")
    first = ws.episodes.create("زمان چیست", season_id=season.id)
    episode = ws.episodes.create("پیکان زمان", season_id=season.id)
    ws.episodes.set_brief(episode.id, ScriptBrief(about="چرا گذشته را به یاد می‌آوریم", depth=2))
    ws.episode_notes.create(episode.id, "شروع", "آنتروپی همیشه بالا می‌رود.")
    todo = ws.episode_notes.create(episode.id, "کارها", "میکروفون را عوض کنم")
    idea = ws.ideas.create("بولتزمن و مغزهای شناور")
    ws.episodes.link(episode.id, LinkKind.IDEA, idea.id, True)

    material = ws.script_prompt.material(episode.id)
    assert [(e.title, e.depth) for e in material.season.before] == [(first.title, 0)]
    brief = replace(ws.episodes.get(episode.id).brief, left_out_notes=frozenset({todo.id}))
    prompt = build_prompt(material, brief)

    for expected in ("پیکان زمان", "چرا گذشته", "زمان از نگاه فیزیک", "آنتروپی", "بولتزمن"):
        assert expected in prompt
    assert "میکروفون" not in prompt  # a note left out of the draft
    assert "پلهٔ ۲ از ۵" in prompt
    assert "درستی‌سنجی" in prompt and "منتظر تأیید" in prompt


def test_without_a_draft_there_is_nothing_of_mine_to_check() -> None:
    prompt = build_prompt(ScriptMaterial(title="اپیزود"), ScriptBrief(minutes=0))
    assert "درستی‌سنجی" not in prompt
    assert "## مدت" not in prompt
    assert "صدای انسانی" in prompt
    assert "## قالب: تک‌گویی" in prompt
    assert "شیوهٔ روایت" not in prompt  # plain talk: no style asked for


def test_previous_summaries_and_the_readme_go_in_unless_turned_off(ws) -> None:
    season = ws.seasons.create("فصل زمان")
    ws.seasons.write_brief(season.id, "هدف: زمان را از نو ببینیم", "برای شنونده")
    first = ws.episodes.create("زمان چیست", season_id=season.id)
    ws.episodes.set_summary(first.id, "گفتیم زمان نسبی است.")
    episode = ws.episodes.create("پیکان زمان", season_id=season.id)
    ws.episodes.create("پایان زمان", season_id=season.id)

    material = ws.script_prompt.material(episode.id)
    assert [e.title for e in material.season.after] == ["پایان زمان"]
    prompt = build_prompt(material, ScriptBrief())
    for expected in ("هدف: زمان", "گفتیم زمان نسبی است", "پایان زمان"):
        assert expected in prompt
    assert "برای شنونده" not in prompt  # the about is for listeners

    off = ScriptBrief(season_readme=False, previous_summaries=False)
    prompt = build_prompt(material, off)
    assert "هدف: زمان" not in prompt and "گفتیم" not in prompt
    assert "زمان چیست" in prompt  # its title still goes in
    assert ScriptBrief.from_dict(off.to_dict()) == off
