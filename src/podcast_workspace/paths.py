"""Filesystem locations. The data directory lives in %APPDATA%\\PodcastWorkspace.

Set PODCAST_WORKSPACE_HOME to point the app at a different data directory
(useful for development and throwaway runs).
"""

import os
from pathlib import Path

APP_DIR_NAME = "PodcastWorkspace"
DB_FILE_NAME = "workspace.db"
LOG_FILE_NAME = "app.log"


def data_dir() -> Path:
    override = os.environ.get("PODCAST_WORKSPACE_HOME")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / APP_DIR_NAME if appdata else Path.home() / f".{APP_DIR_NAME}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    return data_dir() / DB_FILE_NAME


def log_path() -> Path:
    return data_dir() / LOG_FILE_NAME


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def resources_dir() -> Path:
    return package_dir() / "resources"


def _subdir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def bale_voices_dir() -> Path:
    """Voice messages received through the Bale bot."""
    return _subdir("bale_voices")


def voices_dir() -> Path:
    """The workspace's own copy of every audio file added from elsewhere (the audio
    folder, the file picker, a drop), so deleting the original loses nothing."""
    return _subdir("voices")  # services/voice_store.STORE_DIR


def library_dir() -> Path:
    """Audio files restored from an export whose original path no longer exists."""
    return _subdir("library")


def backups_dir() -> Path:
    """Automatic database snapshots taken before an import replaces everything."""
    return _subdir("backups")


def models_dir() -> Path:
    """Downloaded faster-whisper models."""
    return _subdir("models")
