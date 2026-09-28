"""The audio source folder: where the recording program leaves its files.

Everything in it is shown for review without being stored. A file enters the database
only when the user adds it (a normal voice import, which copies it into the workspace's
store), so listening to a take and deciding it is not worth keeping leaves no trace in
the workspace — and once it is added, the folder can be cleared without losing it.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport, VoiceService
from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.services.voice_store import NameChoice, path_key, same_file

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
        # A voice in the trash is still the workspace's: its file is not offered again.
        voices = self._voices.list_all(include_trashed=True)
        known = {path_key(v.file_path) for v in voices}
        # A file copied into the store is known for as long as it is that same file: a
        # recorder that reuses the name makes a new take, which is offered.
        copies = {path_key(v.source_path): Path(v.file_path) for v in voices if v.source_path}
        found: list[SourceFile] = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                key = path_key(path)
                if key in known or (key in copies and same_file(copies[key], path)):
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

    def add(self, path: Path, choice: NameChoice | None = None) -> Voice | None:
        """Bring one file into the workspace; `choice` is the answer when a voice already
        has its name (`VoiceService.name_conflicts`). None when that answer was to skip it.
        Blocking (copies and probes the file): call it off the UI thread."""
        path = path.resolve()
        report: ImportReport = self._voices.import_files(
            [path], {path: choice} if choice is not None else None
        )
        if report.imported:
            return report.imported[0]
        if report.skipped:
            return None
        if report.failed:
            raise OSError(report.failed[0][1])
        # It was there already.
        for voice in self._voices.list_all(include_trashed=True):
            if path_key(voice.file_path) == path_key(path) or (
                voice.source_path and path_key(voice.source_path) == path_key(path)
            ):
                return voice
        raise FileNotFoundError(str(path))
