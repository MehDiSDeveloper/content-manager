"""Audio folder: the files the recording program left, reviewed before any of them is kept.

Reads the folder live (a file watcher, and again whenever the page comes up) and lists
every audio file that is not in the workspace yet. Nothing here is stored: a file can be
played as often as needed and then either added — a normal voice import, after which it
leaves this list and gets its tags and notes on the Voices page — or simply left alone.

A take not worth keeping can be removed from the list (Delete: the file stays on the disk,
and «پنهان‌شده‌ها» under the list brings it back) or deleted from the disk (Shift+Delete:
to the Windows Recycle Bin, after a confirmation).
"""

import contextlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.source_folder import SourceFile
from podcast_workspace.services.voice_store import NameChoice
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import ID_ROLE, ListPage, Row
from podcast_workspace.ui.pages.content_pages import PathLabel
from podcast_workspace.ui.player.player_widget import PlayerWidget, install_player_keys
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    format_datetime,
    local_digits,
    run_async,
    show_error,
)
from podcast_workspace.ui.widgets.key_hint import add_key_hint
from podcast_workspace.ui.widgets.name_conflict import ask_name_choices

WATCH_DELAY_MS = 400  # a recorder writes in bursts; settle before reading the folder
# The player's decoder lets go of a file a moment after it is closed, and Windows will not
# delete a file that is still open: deleting tries again for a little while.
DELETE_RETRY_MS = 250
DELETE_ATTEMPTS = 8


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
        self._hidden_view = False  # the list shows the files taken off it
        # One accent button per screen: here that is "Add to workspace".
        self.primary.setObjectName("")
        self.primary.setToolTip(strings.SOURCE_CHOOSE_TOOLTIP)
        record = QPushButton(strings.WS_RECORD, objectName="recordButton")
        record.setToolTip(strings.WS_RECORD_TOOLTIP)
        record.clicked.connect(self.record_requested)
        header = self.header
        header.insertWidget(header.indexOf(self.primary), record)
        add_key_hint(header, record, "Ctrl+R")

        # One elided line (the folder is reference information), copied on click.
        self.folder_label = PathLabel()
        side = self.list_side.layout()
        side.insertWidget(side.indexOf(self.status), self.folder_label)
        # Under the list: the way back to what was taken off it, there only when needed.
        self.hidden_toggle = QToolButton(objectName="toggleChip", checkable=True)
        self.hidden_toggle.setToolTip(strings.SOURCE_HIDDEN_TOGGLE_TOOLTIP)
        self.hidden_toggle.toggled.connect(self._set_hidden_view)
        self.hidden_toggle.hide()
        side.addWidget(self.hidden_toggle, 0, Qt.AlignmentFlag.AlignLeading)

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
        self.hint = QLabel(strings.SOURCE_HINT, objectName="muted")
        self.hint.setWordWrap(True)
        col.addWidget(self.hint)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.add_button = QPushButton(strings.SOURCE_ADD, objectName="primary")
        self.add_button.setToolTip(strings.SOURCE_ADD_TOOLTIP)
        self.add_button.clicked.connect(lambda: self.add_current(open_after=False))
        actions.addWidget(self.add_button)
        add_key_hint(actions, self.add_button, "Ctrl+Enter")
        self.add_open_button = QPushButton(strings.SOURCE_ADD_OPEN)
        self.add_open_button.setToolTip(strings.SOURCE_ADD_OPEN_TOOLTIP)
        self.add_open_button.clicked.connect(lambda: self.add_current(open_after=True))
        actions.addWidget(self.add_open_button)
        actions.addStretch(1)
        show = QPushButton(strings.VOICE_SHOW_IN_FOLDER)
        show.clicked.connect(self._show_in_folder)
        actions.addWidget(show)
        col.addLayout(actions)
        removal = QHBoxLayout()
        removal.setSpacing(8)
        self.hide_button = QPushButton(strings.SOURCE_HIDE)
        self.hide_button.clicked.connect(self.toggle_hidden_current)
        removal.addWidget(self.hide_button)
        add_key_hint(removal, self.hide_button, "Delete")
        self.delete_button = QPushButton(strings.SOURCE_DELETE, objectName="danger")
        self.delete_button.setToolTip(strings.SOURCE_DELETE_TOOLTIP)
        self.delete_button.clicked.connect(self.delete_current)
        removal.addWidget(self.delete_button)
        add_key_hint(removal, self.delete_button, "Shift+Delete")
        removal.addStretch(1)
        col.addLayout(removal)
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
        pending: list[SourceFile] = []
        hidden: list[SourceFile] = []
        try:
            listing = self._ws.source.listing()
        except OSError:
            self.status.setText(strings.SOURCE_FOLDER_MISSING.format(path=folder))
        else:
            pending, hidden = listing.pending, listing.hidden
            if self.status.text().startswith(strings.SOURCE_FOLDER_MISSING.split("{")[0]):
                self.status.setText("")  # the folder is back
        self.folder_label.set_path(str(folder) if folder else "")
        self.folder_label.setVisible(folder is not None)
        if self._hidden_view and not hidden:
            self._leave_hidden_view()  # the last one was put back, added or deleted
        count = local_digits(len(hidden))
        self.hidden_toggle.setText(strings.SOURCE_HIDDEN_TOGGLE.format(n=count))
        self.hidden_toggle.setVisible(bool(hidden))
        files = hidden if self._hidden_view else pending
        if folder is None:
            self._empty_text = strings.SOURCE_NO_FOLDER
        elif self._hidden_view:
            self._empty_text = strings.SOURCE_HIDDEN_EMPTY
        else:
            self._empty_text = strings.SOURCE_EMPTY
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
        """Delete takes the file off the list (among the hidden ones, puts it back); the
        disk is Shift+Delete's."""
        self.toggle_hidden_current()

    def row_actions(self, item_id: int) -> list[tuple[str, Callable[[], None]]]:
        hide = strings.SOURCE_UNHIDE if self._hidden_view else strings.SOURCE_HIDE
        return [
            (strings.SOURCE_ADD, lambda: self.add_current(open_after=False)),
            (hide, self.toggle_hidden_current),
            (strings.SOURCE_DELETE, self.delete_current),
        ]

    @staticmethod
    def _id_of(item: QListWidgetItem) -> int:
        return int(item.data(ID_ROLE))

    def _neighbour_id(self) -> int | None:
        """The row that takes the current one's place when it leaves the list, so a
        session can be reviewed top to bottom."""
        row = self.list.currentRow()
        neighbour = self.list.item(row + 1) or self.list.item(row - 1)
        return self._id_of(neighbour) if neighbour is not None else None

    def _sync_buttons(self) -> None:
        enabled = self._file is not None and not self._busy
        for button in (self.add_button, self.add_open_button, self.hide_button):
            button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        hidden = self._hidden_view
        self.hide_button.setText(strings.SOURCE_UNHIDE if hidden else strings.SOURCE_HIDE)
        self.hide_button.setToolTip(
            strings.SOURCE_UNHIDE_TOOLTIP if hidden else strings.SOURCE_HIDE_TOOLTIP
        )
        self.hint.setText(strings.SOURCE_HIDDEN_HINT if hidden else strings.SOURCE_HINT)

    def _flash(self, message: str) -> None:
        # The mark keeps the UI's direction when the message opens with a Latin file name.
        self.status.flash(strings.DIRECTION_MARK + message)

    # hidden files ------------------------------------------------------------------------
    def _set_hidden_view(self, on: bool) -> None:
        if on == self._hidden_view:
            return
        self._hidden_view = on
        self.clear_filter(reload=False)
        self.refresh()
        self._sync_buttons()
        self.list.setFocus()

    def _leave_hidden_view(self) -> None:
        self._hidden_view = False
        self.hidden_toggle.blockSignals(True)
        self.hidden_toggle.setChecked(False)
        self.hidden_toggle.blockSignals(False)
        self._sync_buttons()

    def toggle_hidden_current(self) -> None:
        """Take the file off the list, or — among the hidden ones — put it back."""
        file = self._file
        if file is None or self._busy:
            return
        next_id = self._neighbour_id()
        try:
            if self._hidden_view:
                self._ws.source.unhide(file.path)
                message = strings.SOURCE_UNHIDDEN_DONE
            else:
                self._ws.source.hide(file.path)
                message = strings.SOURCE_HIDDEN_DONE
        except OSError as exc:  # gone from the disk meanwhile
            self.refresh()
            show_error(self, exc)
            return
        self._flash(message.format(name=file.name))
        self.refresh(select_id=next_id)
        self.pending_changed.emit()

    # deleting from the disk --------------------------------------------------------------
    def delete_current(self) -> None:
        """To the Windows Recycle Bin, after asking; permanently only if that fails and the
        user says so."""
        file = self._file
        if file is None or self._busy:
            return
        text = strings.SOURCE_DELETE_CONFIRM.format(name=file.name)
        if not confirm(self, text, strings.SOURCE_DELETE_ACTION):
            return
        next_id = self._neighbour_id()
        self.player.close_voice()  # its decoder has the file open
        self._busy = True
        self._sync_buttons()
        self.status.setText(strings.SOURCE_DELETING)
        self._try_delete(file, next_id, DELETE_ATTEMPTS)

    def _try_delete(self, file: SourceFile, next_id: int | None, attempts: int) -> None:
        path = file.path
        if not path.exists() or QFile.moveToTrash(str(path)):
            self._on_deleted(strings.SOURCE_DELETED.format(name=file.name), next_id)
            return
        if attempts > 1:
            QTimer.singleShot(
                DELETE_RETRY_MS, lambda: self._try_delete(file, next_id, attempts - 1)
            )
            return
        # No Recycle Bin on this drive (a network share, some USB sticks), or still in use.
        self._busy = False
        self.status.setText("")
        text = strings.SOURCE_DELETE_NO_BIN.format(name=file.name)
        if confirm(self, text, strings.SOURCE_DELETE_FOREVER):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                show_error(self, exc)
            else:
                self._on_deleted(strings.SOURCE_DELETED_FOREVER.format(name=file.name), next_id)
                return
        self.refresh()  # the file is still there: back in the player
        self._sync_buttons()

    def _on_deleted(self, message: str, next_id: int | None) -> None:
        self._busy = False
        self._flash(message)
        self.refresh(select_id=next_id)
        self._sync_buttons()
        self.pending_changed.emit()

    # adding ------------------------------------------------------------------------------
    def add_current(self, open_after: bool) -> None:
        file = self._file
        if file is None or self._busy:
            return
        conflicts = self._ws.voices.name_conflicts([file.path])
        choice = next(iter(ask_name_choices(self, conflicts).values()), None)
        if choice is NameChoice.SKIP:
            return
        self._busy = True
        self._sync_buttons()
        self.status.setText(strings.SOURCE_ADDING)
        run_async(
            lambda: self._ws.source.add(file.path, choice),
            lambda voice: self._on_added(voice, file, open_after),
            self._on_add_failed,
        )

    def _on_added(self, voice: Voice | None, file: SourceFile, open_after: bool) -> None:
        self._busy = False
        if voice is None:  # left out after all
            self.status.setText("")
            self._sync_buttons()
            return
        self._flash(strings.SOURCE_ADDED.format(name=file.name))
        next_id = self._neighbour_id()
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.list and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if (
                event.key() == Qt.Key.Key_Delete
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self.delete_current()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        self._watch()  # the folder may have been created or restored meanwhile
        super().showEvent(event)

    def pending_count(self) -> int | None:
        try:
            return len(self._ws.source.pending()) if self._ws.source.folder() else None
        except OSError:
            return None
