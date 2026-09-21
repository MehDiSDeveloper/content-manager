"""Audio folder: the files the recording program left, reviewed before any of them is kept.

Reads the folder live (a file watcher, and again whenever the page comes up) and lists
every audio file that is not in the workspace yet. Nothing here is stored: a file can be
played as often as needed and then either added — a normal voice import, after which it
leaves this list and gets its tags and notes on the Voices page — or simply left alone.
"""

import contextlib
import subprocess
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.source_folder import SourceFile
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import ID_ROLE, ListPage, Row
from podcast_workspace.ui.pages.content_pages import PathLabel
from podcast_workspace.ui.player.player_widget import PlayerWidget, install_player_keys
from podcast_workspace.ui.support import (
    AppEvents,
    format_datetime,
    local_digits,
    run_async,
    show_error,
)

WATCH_DELAY_MS = 400  # a recorder writes in bursts; settle before reading the folder


def format_size(size: int) -> str:
    if size >= 1024 * 1024:
        value = f"{size / (1024 * 1024):.1f}".replace(".", strings.DECIMAL_SEPARATOR)
        return strings.SIZE_MB.format(n=local_digits(value))
    return strings.SIZE_KB.format(n=local_digits(max(1, size // 1024)))


class SourcePage(ListPage):
    open_voice = Signal(int)
    record_requested = Signal()
    pending_changed = Signal()  # the folder's contents changed: the nav count is stale

    def __init__(self, workspace: Workspace, events: AppEvents, player: Player) -> None:
        super().__init__(
            strings.SOURCE_TITLE,
            strings.SOURCE_CHOOSE,
            strings.SOURCE_EMPTY,
            filter_placeholder=strings.SOURCE_FILTER_PLACEHOLDER,
        )
        self._ws = workspace
        self._events = events
        # Rows need int ids; a path keeps the same one for as long as the page lives, so
        # the selection survives the folder being re-read.
        self._ids: dict[Path, int] = {}
        self._files: dict[int, SourceFile] = {}
        self._file: SourceFile | None = None
        self._busy = False
        # One accent button per screen: here that is "Add to workspace".
        self.primary.setObjectName("")
        self.primary.setToolTip(strings.SOURCE_CHOOSE_TOOLTIP)
        record = QPushButton(strings.WS_RECORD, objectName="recordButton")
        record.setToolTip(strings.WS_RECORD_TOOLTIP)
        record.clicked.connect(self.record_requested)
        header = self._header_layout()
        header.insertWidget(header.indexOf(self.primary), record)

        # One elided line (the folder is reference information), copied on click.
        self.folder_label = PathLabel()
        side = self.list_side.layout()
        side.insertWidget(1, self.folder_label)

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        self.name = QLabel(objectName="editorTitle")
        self.name.setWordWrap(True)
        col.addWidget(self.name)
        self.meta = QLabel(objectName="muted")
        col.addWidget(self.meta)
        self.player = PlayerWidget(player)
        col.addSpacing(6)
        col.addWidget(self.player)
        hint = QLabel(strings.SOURCE_HINT, objectName="muted")
        hint.setWordWrap(True)
        col.addWidget(hint)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.add_button = QPushButton(strings.SOURCE_ADD, objectName="primary")
        self.add_button.setToolTip(strings.SOURCE_ADD_TOOLTIP)
        self.add_button.clicked.connect(lambda: self.add_current(open_after=False))
        actions.addWidget(self.add_button)
        self.add_open_button = QPushButton(strings.SOURCE_ADD_OPEN)
        self.add_open_button.setToolTip(strings.SOURCE_ADD_OPEN_TOOLTIP)
        self.add_open_button.clicked.connect(lambda: self.add_current(open_after=True))
        actions.addWidget(self.add_open_button)
        actions.addStretch(1)
        show = QPushButton(strings.VOICE_SHOW_IN_FOLDER)
        show.clicked.connect(self._show_in_folder)
        actions.addWidget(show)
        col.addLayout(actions)
        col.addStretch(1)

        install_player_keys(
            self, player, (("Ctrl+Return", lambda: self.add_current(open_after=False)),)
        )
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _p: self._reread.start())
        self._reread = QTimer(self, singleShot=True, interval=WATCH_DELAY_MS)
        self._reread.timeout.connect(self._on_folder_changed)
        events.data_changed.connect(self._on_data_changed)
        self._watch()

    def _header_layout(self) -> QHBoxLayout:
        layout = self.list_side.layout().itemAt(0).layout()
        assert isinstance(layout, QHBoxLayout)
        return layout

    # the folder --------------------------------------------------------------------------
    def _watch(self) -> None:
        """Follow the folder and its subfolders, so a file saved by the recorder shows up
        without the user asking for it."""
        watched = self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)
        folders = [str(p) for p in self._ws.source.subfolders()]
        if folders:
            self._watcher.addPaths(folders)

    def _on_folder_changed(self) -> None:
        self._watch()  # a new subfolder needs watching too
        self.pending_changed.emit()
        if self.isVisible() and not self._busy:
            self.refresh()

    def _on_data_changed(self) -> None:
        """A voice removed from the workspace belongs back in this list."""
        self.pending_changed.emit()

    def primary_action(self) -> None:
        """The list's own button: pick the folder to read."""
        folder = self._ws.source.folder()
        chosen = QFileDialog.getExistingDirectory(
            self, strings.SOURCE_DIALOG, str(folder) if folder else ""
        )
        if not chosen:
            return
        self._ws.source.set_folder(Path(chosen))
        self._ids.clear()
        self._watch()
        self.clear_filter(reload=False)
        self.refresh()
        self.pending_changed.emit()

    # the list ----------------------------------------------------------------------------
    def rows(self) -> list[Row]:
        folder = self._ws.source.folder()
        try:
            files = self._ws.source.pending()
        except OSError:
            files = []
            self.status.setText(strings.SOURCE_FOLDER_MISSING.format(path=folder))
        else:
            if self.status.text().startswith(strings.SOURCE_FOLDER_MISSING.split("{")[0]):
                self.status.setText("")  # the folder is back
        self.folder_label.set_path(str(folder) if folder else "")
        self.folder_label.setVisible(folder is not None)
        self._empty_text = strings.SOURCE_NO_FOLDER if folder is None else strings.SOURCE_EMPTY
        self._files = {}
        rows: list[Row] = []
        for file in files:
            item_id = self._ids.setdefault(file.path, len(self._ids) + 1)
            self._files[item_id] = file
            rows.append(Row(item_id, file.name, self._subtitle(file, folder)))
        return rows

    @staticmethod
    def _subtitle(file: SourceFile, folder: Path | None) -> str:
        parts = [format_datetime(file.modified), format_size(file.size)]
        if folder is not None and file.path.parent != folder:
            with contextlib.suppress(ValueError):
                relative = file.path.parent.relative_to(folder)
                parts.append(strings.SOURCE_IN_SUBFOLDER.format(folder=relative))
        return "  ·  ".join(parts)

    def show_item(self, item_id: int) -> None:
        file = self._files.get(item_id)
        if file is None:
            return
        self._file = file
        self.name.setText(file.name)
        self.meta.setText(self._subtitle(file, self._ws.source.folder()))
        self.meta.setToolTip(str(file.path))
        # Negative ids: never mistaken for a voice's, and one per file.
        self.player.open_voice(-item_id, file.path, 0)
        self._sync_buttons()

    def clear_editor(self) -> None:
        self._file = None
        self.player.close_voice()

    def focus_editor(self) -> None:
        self.add_button.setFocus()

    def delete_item(self, item_id: int) -> None:
        """Delete means nothing here: this page never removes a file from the disk."""

    @staticmethod
    def _id_of(item: QListWidgetItem) -> int:
        return int(item.data(ID_ROLE))

    def _sync_buttons(self) -> None:
        enabled = self._file is not None and not self._busy
        self.add_button.setEnabled(enabled)
        self.add_open_button.setEnabled(enabled)

    # adding ------------------------------------------------------------------------------
    def add_current(self, open_after: bool) -> None:
        file = self._file
        if file is None or self._busy:
            return
        self._busy = True
        self._sync_buttons()
        self.status.setText(strings.SOURCE_ADDING)
        run_async(
            lambda: self._ws.source.add(file.path),
            lambda voice: self._on_added(voice, file, open_after),
            self._on_add_failed,
        )

    def _on_added(self, voice: Voice, file: SourceFile, open_after: bool) -> None:
        self._busy = False
        self.status.setText(strings.SOURCE_ADDED.format(name=file.name))
        QTimer.singleShot(6000, lambda: self.status.setText(""))
        # The next file down takes its place, so a session can be reviewed top to bottom.
        row = self.list.currentRow()
        neighbour = self.list.item(row + 1) or self.list.item(row - 1)
        next_id = self._id_of(neighbour) if neighbour is not None else None
        self._events.data_changed.emit()
        self.refresh(select_id=next_id)
        self._sync_buttons()
        if open_after and voice.id is not None:
            self.open_voice.emit(voice.id)

    def _on_add_failed(self, exc: BaseException) -> None:
        self._busy = False
        self.status.setText("")
        self._sync_buttons()
        show_error(self, exc)

    def _show_in_folder(self) -> None:
        if self._file is None:
            return
        path = self._file.path
        if path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif path.parent.exists():
            subprocess.Popen(["explorer", str(path.parent)])

    def showEvent(self, event: QShowEvent) -> None:
        self._watch()  # the folder may have been created or restored meanwhile
        super().showEvent(event)

    def pending_count(self) -> int | None:
        try:
            return len(self._ws.source.pending()) if self._ws.source.folder() else None
        except OSError:
            return None
