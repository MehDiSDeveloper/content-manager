"""Editing an episode's fields from the workspace."""

import pytest

from podcast_workspace.domain.entities import EpisodeStatus
from podcast_workspace.services.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_WORKSPACE_HOME", str(tmp_path))
    workspace = Workspace.open(tmp_path / "w.db")
    yield workspace
    workspace.close()


def test_a_status_that_arrives_as_plain_text_is_saved(ws) -> None:
    # A QComboBox gives its StrEnum data back as a str.
    episode = ws.episodes.create("قسمت اول")
    saved = ws.episodes.update(episode.id, title="قسمت یکم", status="outline", next_action="")
    assert saved.status is EpisodeStatus.OUTLINE
    assert ws.episodes.set_status(episode.id, "edited").status is EpisodeStatus.EDITED
