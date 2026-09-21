"""Season dialogs shared by the Episodes list and the episode workspace."""

from PySide6.QtWidgets import QInputDialog, QLineEdit, QWidget

from podcast_workspace.domain.entities import Season
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits, show_error


def _ask(parent: QWidget, title: str, text: str) -> str | None:
    value, ok = QInputDialog.getText(
        parent, title, strings.SEASON_NAME_PROMPT, QLineEdit.EchoMode.Normal, text
    )
    return value.strip() if ok and value.strip() else None


def create_season(parent: QWidget, workspace: Workspace) -> Season | None:
    """Ask for a name (offering the next number) and make the season."""
    count = len(workspace.seasons.list_all())
    title = _ask(
        parent,
        strings.SEASON_NEW_TITLE,
        strings.SEASON_DEFAULT_TITLE.format(n=local_digits(count + 1)),
    )
    if title is None:
        return None
    try:
        return workspace.seasons.create(title)
    except Exception as exc:
        show_error(parent, exc)
        return None


def rename_season(parent: QWidget, workspace: Workspace, season: Season) -> bool:
    title = _ask(parent, strings.SEASON_RENAME_TITLE, season.title)
    if title is None or season.id is None:
        return False
    try:
        workspace.seasons.rename(season.id, title)
    except Exception as exc:
        show_error(parent, exc)
        return False
    return True
