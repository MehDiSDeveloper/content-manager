"""User preferences persisted in the `settings` table."""

import base64
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.repositories.unit_of_work import UnitOfWork


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


THEME_KEY = "ui.theme"
GEOMETRY_KEY = "ui.window_geometry"
RECORDER_KEY = "recording.program_path"
BALE_TOKEN_KEY = "bale.token"
BALE_ENABLED_KEY = "bale.enabled"
BALE_OWNER_KEY = "bale.owner"
BALE_OFFSET_KEY = "bale.update_offset"
WHISPER_MODEL_KEY = "transcription.model"
WHISPER_MODEL_DIR_KEY = "transcription.model_dir"

DEFAULT_WHISPER_MODEL = "large-v3-turbo"


@dataclass(frozen=True)
class BotOwner:
    """The only Bale chat the bot accepts items from (claimed by the first private chat)."""

    chat_id: int
    name: str


class SettingsService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _get(self, key: str) -> Any:
        with UnitOfWork(self._session_factory) as uow:
            return uow.settings.get(key)

    def _set(self, key: str, value: Any) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.settings.set(key, value)

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

    def recorder_path(self) -> str:
        """Path of the user's external recording program ("" = not set)."""
        with UnitOfWork(self._session_factory) as uow:
            value = uow.settings.get(RECORDER_KEY)
        return value if isinstance(value, str) else ""

    def set_recorder_path(self, path: str) -> None:
        with UnitOfWork(self._session_factory) as uow:
            uow.settings.set(RECORDER_KEY, path.strip())

    # Bale bot --------------------------------------------------------------------------
    def bale_token(self) -> str:
        value = self._get(BALE_TOKEN_KEY)
        return value if isinstance(value, str) else ""

    def set_bale_token(self, token: str) -> None:
        token = token.strip()
        if token != self.bale_token():
            self._set(BALE_TOKEN_KEY, token)
            self._set(BALE_OFFSET_KEY, None)  # offsets belong to one bot
            self._set(BALE_OWNER_KEY, None)

    def bale_enabled(self) -> bool:
        return self._get(BALE_ENABLED_KEY) is True

    def set_bale_enabled(self, enabled: bool) -> None:
        self._set(BALE_ENABLED_KEY, bool(enabled))

    def bale_owner(self) -> BotOwner | None:
        value = self._get(BALE_OWNER_KEY)
        if isinstance(value, dict) and isinstance(value.get("chat_id"), int):
            return BotOwner(value["chat_id"], str(value.get("name") or ""))
        return None

    def set_bale_owner(self, owner: BotOwner | None) -> None:
        self._set(
            BALE_OWNER_KEY,
            None if owner is None else {"chat_id": owner.chat_id, "name": owner.name},
        )

    def bale_offset(self) -> int | None:
        value = self._get(BALE_OFFSET_KEY)
        return value if isinstance(value, int) else None

    def set_bale_offset(self, offset: int) -> None:
        self._set(BALE_OFFSET_KEY, offset)

    # transcription ---------------------------------------------------------------------
    def whisper_model(self) -> str:
        value = self._get(WHISPER_MODEL_KEY)
        return value if isinstance(value, str) and value else DEFAULT_WHISPER_MODEL

    def set_whisper_model(self, name: str) -> None:
        self._set(WHISPER_MODEL_KEY, name)

    def whisper_model_dir(self) -> str:
        """A user-provided CTranslate2 model folder; "" = use the managed download."""
        value = self._get(WHISPER_MODEL_DIR_KEY)
        return value if isinstance(value, str) else ""

    def set_whisper_model_dir(self, path: str) -> None:
        self._set(WHISPER_MODEL_DIR_KEY, path.strip())
