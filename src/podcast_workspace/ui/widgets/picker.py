"""A list to choose from: type to filter, Enter takes the selection.

Used to link voices and ideas to an episode, and to put ideas into an episode.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.text import normalize_for_match
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import SUBTITLE_ROLE, TwoLineDelegate

ID_ROLE = Qt.ItemDataRole.UserRole


class PickerDialog(QDialog):
    """Choose from a list of rows (id, title, subtitle); several can be taken at once."""

    def __init__(self, parent: QWidget, title: str, rows: list[tuple[int, str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 520)
        self._rows = rows
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(12)
        col.addWidget(QLabel(title, objectName="dialogTitle"))
        self.filter = QLineEdit(placeholderText=strings.WS_PICK_FILTER)
        self.filter.textChanged.connect(self._fill)
        self.filter.installEventFilter(self)
        col.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        col.addWidget(self.list, 1)
        buttons = QDialogButtonBox()
        add = buttons.addButton(strings.WS_PICK_ADD, QDialogButtonBox.ButtonRole.AcceptRole)
        add.setObjectName("primary")
        buttons.addButton(strings.CANCEL, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._fill("")

    def _fill(self, query: str) -> None:
        needle = normalize_for_match(query)
        self.list.clear()
        for item_id, title, subtitle in self._rows:
            if needle and needle not in normalize_for_match(f"{title} {subtitle}"):
                continue
            item = QListWidgetItem(title)
            item.setData(ID_ROLE, item_id)
            item.setData(SUBTITLE_ROLE, subtitle)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            empty = QListWidgetItem(strings.WS_PICK_EMPTY)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)

    def chosen(self) -> list[int]:
        return [int(i.data(ID_ROLE)) for i in self.list.selectedItems() if i.data(ID_ROLE)]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.filter and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.list.setFocus()
                self.list.keyPressEvent(event)
                return True
        return super().eventFilter(watched, event)
