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
    assert (season.readme, season.about) == ("", "")


def test_writing_the_brief_is_stored_and_one_undo_step(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    for readme in ("د", "دربارهٔ", "دربارهٔ اعتماد"):
        ws.seasons.write_brief(season.id, readme, "۱. شروع")
    stored = ws.seasons.get(season.id)
    assert (stored.readme, stored.about) == ("دربارهٔ اعتماد", "۱. شروع")

    ws.history.undo()
    stored = ws.seasons.get(season.id)
    assert (stored.readme, stored.about) == ("", "")
    ws.history.redo()
    assert ws.seasons.get(season.id).readme == "دربارهٔ اعتماد"


def test_an_unchanged_brief_records_nothing(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "")
    ws.history.undo()  # the writing run
    ws.history.redo()
    ws.seasons.write_brief(season.id, "هدف", "")
    ws.history.undo()
    assert ws.seasons.get(season.id).readme == ""


def test_renaming_keeps_the_brief(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    ws.seasons.rename(season.id, "فصل یکم")
    stored = ws.seasons.get(season.id)
    assert (stored.title, stored.readme, stored.about) == ("فصل یکم", "هدف", "ساختار")


def test_undoing_a_delete_brings_the_brief_back(ws) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    ws.seasons.delete(season.id)
    ws.history.undo()
    (restored,) = ws.seasons.list_all()
    assert (restored.readme, restored.about) == ("هدف", "ساختار")


def test_the_brief_survives_an_export_and_restore(ws, tmp_path) -> None:
    season = ws.seasons.create("فصل ۱")
    ws.seasons.write_brief(season.id, "هدف", "ساختار")
    target = tmp_path / "backup.zip"
    ws.backup.export(target)
    ws.seasons.write_brief(season.id, "", "")

    ws.backup.restore(target)
    stored = ws.seasons.get(season.id)
    assert (stored.readme, stored.about) == ("هدف", "ساختار")


def test_an_export_from_before_the_readme_keeps_the_old_brief(ws, tmp_path) -> None:
    import json
    import zipfile

    season = ws.seasons.create("فصل ۱")
    target = tmp_path / "backup.zip"
    ws.backup.export(target)
    with zipfile.ZipFile(target) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    name = next(n for n in files if n.endswith(".json"))
    data = json.loads(files[name])
    (old,) = data["seasons"]
    del old["readme"], old["about"]
    old.update(summary="هدف", outline="ساختار")
    files[name] = json.dumps(data, ensure_ascii=False).encode()
    with zipfile.ZipFile(target, "w") as archive:
        for n, content in files.items():
            archive.writestr(n, content)

    ws.backup.restore(target)
    stored = ws.seasons.get(season.id)
    assert (stored.readme, stored.about) == ("هدف\n\nساختار", "")


def test_an_episode_summary_is_stored_undoable_and_exported(ws, tmp_path) -> None:
    episode = ws.episodes.create("اپیزود ۱")
    for text in ("د", "دربارهٔ اعتماد"):
        ws.episodes.set_summary(episode.id, text)
    assert ws.episodes.get(episode.id).summary == "دربارهٔ اعتماد"
    ws.episodes.update(episode.id, title="اپیزود یکم", status=episode.status, next_action="")
    assert ws.episodes.get(episode.id).summary == "دربارهٔ اعتماد"
    ws.history.undo()  # the rename
    ws.history.undo()  # the whole writing run
    assert ws.episodes.get(episode.id).summary == ""
    ws.history.redo()

    target = tmp_path / "backup.zip"
    ws.backup.export(target)
    ws.episodes.set_summary(episode.id, "")
    ws.backup.restore(target)
    assert ws.episodes.get(episode.id).summary == "دربارهٔ اعتماد"
