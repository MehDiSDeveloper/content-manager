"""Filesystem locations. The data directory lives in %APPDATA%\\PodcastWorkspace.

Set PODCAST_WORKSPACE_HOME to point the app at a different data directory
(useful for development and throwaway runs).
"""

import os
from pathlib import Path

APP_DIR_NAME = "PodcastWorkspace"
DB_FILE_NAME = "workspace.db"


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


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def resources_dir() -> Path:
    return package_dir() / "resources"
