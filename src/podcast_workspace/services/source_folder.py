"""The audio source folder: where the recording program leaves its files.

Everything in it is shown for review without being stored. A file enters the database
only when the user adds it (a normal voice import), so listening to a take and deciding
it is not worth keeping leaves no trace in the workspace.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport, VoiceService
from podcast_workspace.services.settings_service import SettingsService

# A folder picked by mistake (a whole drive, Documents) must not hang the page.
MAX_FILES = 3000


@dataclass(frozen=True)
class SourceFile:
    path: Path
    size: int
    modified: datetime

    @property
    def name(self) -> str:
        return self.path.name


def _key(path: Path | str) -> str:
    """Windows paths compare case-insensitively and with either slash; resolved the way
    an import stores them."""
    return os.path.normcase(str(Path(path).resolve()))


class SourceFolderService:
    def __init__(self, settings: SettingsService, voices: VoiceService) -> None:
        self._settings = settings
        self._voices = voices

    def folder(self) -> Path | None:
        value = self._settings.source_folder()
        return Path(value) if value else None

    def set_folder(self, path: Path) -> None:
        self._settings.set_source_folder(str(path))

    def pending(self) -> list[SourceFile]:
        """Audio files in the folder (and its subfolders) not yet in the workspace, newest
        first. Empty when no folder is set; FileNotFoundError when it has gone."""
        folder = self.folder()
        if folder is None:
            return []
        if not folder.is_dir():
            raise FileNotFoundError(str(folder))
        known = {_key(v.file_path) for v in self._voices.list_all()}
        found: list[SourceFile] = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS or _key(path) in known:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue  # vanished or locked while we looked
                modified = datetime.fromtimestamp(stat.st_mtime, UTC)
                found.append(SourceFile(path, stat.st_size, modified))
                if len(found) >= MAX_FILES:
                    break
            if len(found) >= MAX_FILES:
                break
        found.sort(key=lambda f: f.modified, reverse=True)
        return found

    def subfolders(self) -> list[Path]:
        """The folder and every folder under it, for the file watcher."""
        folder = self.folder()
        if folder is None or not folder.is_dir():
            return []
        found = [folder]
        for root, dirs, _files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found += [Path(root) / d for d in dirs]
            if len(found) > 200:
                break
        return found

    def add(self, path: Path) -> Voice:
        """Bring one file into the workspace. Blocking (probes the file): call it off the
        UI thread."""
        report: ImportReport = self._voices.import_files([path])
        if report.imported:
            return report.imported[0]
        if report.failed:
            raise OSError(report.failed[0][1])
        for voice in self._voices.list_all():  # it was there already
            if _key(voice.file_path) == _key(path):
                return voice
        raise FileNotFoundError(str(path))
