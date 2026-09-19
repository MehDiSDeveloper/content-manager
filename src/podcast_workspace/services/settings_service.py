"""User preferences persisted in the `settings` table."""

import base64
from enum import StrEnum

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.repositories.unit_of_work import UnitOfWork


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


THEME_KEY = "ui.theme"
GEOMETRY_KEY = "ui.window_geometry"


class SettingsService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def theme(self) -> Theme | None:
        """None means the user never chose; the UI then follows the system scheme."""
        with UnitOfWork(self._session_factory) as uow:
            value = uow.settings.get(THEME_KEY)
        return Theme(value) if value in {t.value for t in Theme} else None

    def set_theme(self, theme: Theme) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.settings.set(THEME_KEY, theme.value)

    def window_geometry(self) -> bytes | None:
        with UnitOfWork(self._session_factory) as uow:
            value = uow.settings.get(GEOMETRY_KEY)
        return base64.b64decode(value) if isinstance(value, str) else None

    def set_window_geometry(self, geometry: bytes) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.settings.set(GEOMETRY_KEY, base64.b64encode(geometry).decode("ascii"))
