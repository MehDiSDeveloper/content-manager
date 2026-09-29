"""Tag chip, colored dot icons and the fuzzy suggestion list shared by tag pickers."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QWidget,
)

from podcast_workspace.domain.entities import Tag
from podcast_workspace.ui import strings

_dot_cache: dict[str, QIcon] = {}


def color_dot(color: str, size: int = 12) -> QIcon:
    if color not in _dot_cache:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.end()
        _dot_cache[color] = QIcon(pixmap)
    return _dot_cache[color]


class TagChip(QFrame):
    remove_requested = Signal(int)

    def __init__(self, tag: Tag, removable: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tag_id = tag.id or 0
        self.setObjectName("tagChip")
        color = QColor(tag.color)
        self.setStyleSheet(
            "#tagChip { border-radius: 11px; padding: 0 2px;"
            f" background: rgba({color.red()}, {color.green()}, {color.blue()}, 38);"
            f" border: 1px solid rgba({color.red()}, {color.green()}, {color.blue()}, 140); }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4 if removable else 8, 2)
        row.setSpacing(2)
        dot = QLabel()
        dot.setPixmap(color_dot(tag.color, 10).pixmap(10, 10))
        row.addWidget(dot)
        row.addWidget(QLabel(tag.name))
        if removable:
            close = QToolButton(text="×", objectName="chipClose")
            close.setToolTip(strings.TAG_REMOVE_TOOLTIP)
            # Tab reaches it; Backspace in the input never eats an attached tag.
            close.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            close.clicked.connect(lambda: self.remove_requested.emit(self.tag_id))
            row.addWidget(close)


# item data roles
KIND_ROLE = Qt.ItemDataRole.UserRole
VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_TAG = "tag"
KIND_CREATE = "create"


class SuggestionList(QListWidget):
    """Keyboard-driven list of tag suggestions; the owner forwards arrow keys to it."""

    activated_value = Signal(str, object)  # kind, value (tag id or new name)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("suggestions")
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(12, 12))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.itemClicked.connect(self._emit)

    def fill(
        self,
        tags: list[Tag],
        create: tuple[str, str] | None = None,
        max_visible: int = 8,
    ) -> None:
        """`create` = (label, name) adds a trailing 'create new tag' row."""
        self.clear()
        for tag in tags:
            item = QListWidgetItem(color_dot(tag.color), tag.name)
            item.setData(KIND_ROLE, KIND_TAG)
            item.setData(VALUE_ROLE, tag.id)
            self.addItem(item)
        if create is not None:
            item = QListWidgetItem(create[0])
            item.setData(KIND_ROLE, KIND_CREATE)
            item.setData(VALUE_ROLE, create[1])
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            self.addItem(item)
        if self.count():
            self.setCurrentRow(0)
            row_height = self.sizeHintForRow(0)
            self.setFixedHeight(row_height * min(self.count(), max_visible) + 6)
        self.setVisible(self.count() > 0)

    def move(self, delta: int) -> None:
        if self.count():
            self.setCurrentRow((self.currentRow() + delta) % self.count())

    def activate_current(self) -> bool:
        item = self.currentItem()
        if item is None or not self.isVisible():
            return False
        self._emit(item)
        return True

    def _emit(self, item: QListWidgetItem) -> None:
        self.activated_value.emit(item.data(KIND_ROLE), item.data(VALUE_ROLE))
