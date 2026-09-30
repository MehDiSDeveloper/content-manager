"""The audio source folder: where the recording program leaves its files.

Everything in it is shown for review without being stored. A file enters the database
only when the user adds it (a normal voice import, which copies it into the workspace's
store), so listening to a take and deciding it is not worth keeping leaves no trace in
the workspace — and once it is added, the folder can be cleared without losing it.

A take that is not worth keeping can be taken off the list (the file stays where it is,
and can be put back) or deleted from the disk.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport, VoiceService
from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.services.voice_store import (
    MTIME_SLACK_S,
    NameChoice,
    path_key,
    same_file,
)

# A folder picked by mistake (a whole drive, Documents) must not hang the page.
MAX_FILES = 3000


@dataclass(frozen=True)
class SourceListing:
    """What the folder holds that is not in the workspace: the files on the list, and the
    ones taken off it."""

    pending: list["SourceFile"]
    hidden: list["SourceFile"]


@dataclass(frozen=True)
class SourceFile:
    path: Path
    size: int
    modified: datetime

    @property
    def name(self) -> str:
        return self.path.name


def _still_known(copy: Path, original: Path, original_mtime: float) -> bool:
    """The stored copy is of this very file: the same file, or one written from it later
    (saved over with its pauses trimmed). A new take under a reused name is newer than the
    copy of the old one."""
    if same_file(copy, original):
        return True
    try:
        return original_mtime + MTIME_SLACK_S < copy.stat().st_mtime
    except OSError:
        return False


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
        return self.listing().pending

    def listing(self) -> SourceListing:
        """The folder's files not yet in the workspace, newest first, split into the list and
        the files taken off it. Empty when no folder is set; FileNotFoundError when it has
        gone."""
        folder = self.folder()
        if folder is None:
            return SourceListing([], [])
        if not folder.is_dir():
            raise FileNotFoundError(str(folder))
        found, complete = self._scan(folder)
        hidden_marks = self._settings.source_hidden()
        pending: list[SourceFile] = []
        hidden: list[SourceFile] = []
        still_hidden: set[str] = set()
        for file in found:
            key = path_key(file.path)
            mark = hidden_marks.get(key)
            # A new take saved under the same name is a different recording: it is listed.
            if mark is not None and abs(file.modified.timestamp() - mark) <= MTIME_SLACK_S:
                hidden.append(file)
                still_hidden.add(key)
            else:
                pending.append(file)
        if complete:
            self._forget_hidden(folder, hidden_marks, still_hidden)
        return SourceListing(pending, hidden)

    def _scan(self, folder: Path) -> tuple[list[SourceFile], bool]:
        """Every audio file under `folder` not in the workspace, and whether that is all of
        them (False when MAX_FILES cut the walk short)."""
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
                if key in known:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue  # vanished or locked while we looked
                modified = datetime.fromtimestamp(stat.st_mtime, UTC)
                if key in copies and _still_known(copies[key], path, stat.st_mtime):
                    continue
                found.append(SourceFile(path, stat.st_size, modified))
                if len(found) >= MAX_FILES:
                    return self._newest_first(found), False
        return self._newest_first(found), True

    @staticmethod
    def _newest_first(files: list[SourceFile]) -> list[SourceFile]:
        return sorted(files, key=lambda f: f.modified, reverse=True)

    def _forget_hidden(self, folder: Path, marks: dict[str, float], kept: set[str]) -> None:
        """Drop the marks of files under `folder` that are gone, replaced or added, so the
        setting does not grow for ever. Another folder's marks wait for it to come back."""
        prefix = path_key(folder).rstrip(os.sep) + os.sep
        stale = [k for k in marks if k.startswith(prefix) and k not in kept]
        if stale:
            for key in stale:
                del marks[key]
            self._settings.set_source_hidden(marks)

    def hide(self, path: Path) -> None:
        """Take a file off the list; it stays on the disk. It comes back if it is recorded
        over."""
        marks = self._settings.source_hidden()
        marks[path_key(path)] = path.stat().st_mtime
        self._settings.set_source_hidden(marks)

    def unhide(self, path: Path) -> None:
        marks = self._settings.source_hidden()
        if marks.pop(path_key(path), None) is not None:
            self._settings.set_source_hidden(marks)

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
