"""User preferences persisted in the `settings` table."""

import base64
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.repositories.unit_of_work import UnitOfWork


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


class Language(StrEnum):
    FA = "fa"
    EN = "en"


THEME_KEY = "ui.theme"
LANGUAGE_KEY = "ui.language"
SIDEBAR_COMPACT_KEY = "ui.sidebar_compact"
LIST_HIDDEN_KEY = "ui.episode_list_hidden"
FIRST_RUN_KEY = "app.first_run_at"
LAST_BACKUP_KEY = "backup.last_export_at"
BACKUP_SNOOZE_KEY = "backup.reminder_snoozed_until"
BACKUP_INTERVAL_KEY = "backup.reminder_days"
GEOMETRY_KEY = "ui.window_geometry"
RECORDER_KEY = "recording.program_path"
SOURCE_FOLDER_KEY = "voices.source_folder"
SEASON_FILTER_KEY = "ui.episode_season_filter"
BALE_TOKEN_KEY = "bale.token"
BALE_ENABLED_KEY = "bale.enabled"
BALE_OWNER_KEY = "bale.owner"
BALE_OFFSET_KEY = "bale.update_offset"
WHISPER_MODEL_KEY = "transcription.model"
WHISPER_MODEL_DIR_KEY = "transcription.model_dir"
WHISPER_SPEED_KEY = "transcription.seconds_per_audio_second"

DEFAULT_WHISPER_MODEL = "large-v3-turbo"
DEFAULT_BACKUP_INTERVAL_DAYS = 7


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

    def language(self) -> Language | None:
        """None means the user has not chosen yet: the app asks once, on first start."""
        value = self._get(LANGUAGE_KEY)
        return Language(value) if value in {lang.value for lang in Language} else None

    def set_language(self, language: Language) -> None:
        self._set(LANGUAGE_KEY, language.value)

    def sidebar_compact(self) -> bool:
        return self._get(SIDEBAR_COMPACT_KEY) is True

    def set_sidebar_compact(self, compact: bool) -> None:
        self._set(SIDEBAR_COMPACT_KEY, bool(compact))

    def episode_list_hidden(self) -> bool:
        return self._get(LIST_HIDDEN_KEY) is True

    def set_episode_list_hidden(self, hidden: bool) -> None:
        self._set(LIST_HIDDEN_KEY, bool(hidden))

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

    def source_folder(self) -> str:
        """Folder the recording program saves into ("" = not chosen yet)."""
        value = self._get(SOURCE_FOLDER_KEY)
        return value if isinstance(value, str) else ""

    def set_source_folder(self, path: str) -> None:
        self._set(SOURCE_FOLDER_KEY, path.strip())

    def season_filter(self) -> str:
        """Which season the Episodes list shows: "all", "none" or a season id."""
        value = self._get(SEASON_FILTER_KEY)
        return value if isinstance(value, str) and value else "all"

    def set_season_filter(self, value: str) -> None:
        self._set(SEASON_FILTER_KEY, value)

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

    def transcription_speed(self, model: str) -> float | None:
        """Seconds of work per second of audio measured on this machine for a model
        (None = never measured). The progress estimate is built on it."""
        value = self._get(WHISPER_SPEED_KEY)
        speed = value.get(model) if isinstance(value, dict) else None
        return float(speed) if isinstance(speed, int | float) and speed > 0 else None

    def set_transcription_speed(self, model: str, speed: float) -> None:
        value = self._get(WHISPER_SPEED_KEY)
        speeds = dict(value) if isinstance(value, dict) else {}
        speeds[model] = round(speed, 4)
        self._set(WHISPER_SPEED_KEY, speeds)

    # backup reminder -------------------------------------------------------------------
    def _get_datetime(self, key: str) -> datetime | None:
        value = self._get(key)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    def _set_datetime(self, key: str, value: datetime | None) -> None:
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        self._set(key, None if value is None else value.isoformat())

    def first_run_at(self, now: datetime) -> datetime:
        """When the app first ran on this machine; recorded on the first call."""
        value = self._get_datetime(FIRST_RUN_KEY)
        if value is None:
            self._set_datetime(FIRST_RUN_KEY, now)
            return now
        return value

    def last_backup_at(self) -> datetime | None:
        return self._get_datetime(LAST_BACKUP_KEY)

    def set_last_backup_at(self, when: datetime) -> None:
        self._set_datetime(LAST_BACKUP_KEY, when)

    def backup_snoozed_until(self) -> datetime | None:
        return self._get_datetime(BACKUP_SNOOZE_KEY)

    def set_backup_snoozed_until(self, when: datetime | None) -> None:
        self._set_datetime(BACKUP_SNOOZE_KEY, when)

    def backup_interval_days(self) -> int:
        """Days between backup reminders; 0 turns the reminder off."""
        value = self._get(BACKUP_INTERVAL_KEY)
        return value if isinstance(value, int) and value >= 0 else DEFAULT_BACKUP_INTERVAL_DAYS

    def set_backup_interval_days(self, days: int) -> None:
        self._set(BACKUP_INTERVAL_KEY, max(0, int(days)))
