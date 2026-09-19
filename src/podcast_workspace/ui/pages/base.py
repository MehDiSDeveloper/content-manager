"""Master/detail page skeleton shared by Episodes, Voices and Ideas.

Layout (RTL): header [title ........ primary button], body [list | editor].
Keys: Ctrl+N primary action, Delete deletes the selected item (list focused),
Enter in the list moves focus into the editor, Esc in the editor returns to the list.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

RLM = "‏"  # right-to-left mark: fixes base direction of mixed Persian/Latin/digit text


def _rtl(text: str) -> str:
    # RLM around separators stops Persian digits after a Latin word (e.g. "WAV · ۲۸")
    # from joining the Latin run (Unicode bidi rule W7).
    return RLM + text.replace("·", f"{RLM}·{RLM}")


ID_ROLE = Qt.ItemDataRole.UserRole
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
LIST_WIDTH = 340


@dataclass(frozen=True)
class Row:
    item_id: int
    title: str
    subtitle: str = ""


class TwoLineDelegate(QStyledItemDelegate):
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        height = option.fontMetrics.height()
        return QSize(option.rect.width(), height * 2 + 26)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        palette = opt.palette
        title_color = palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        muted = palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.PlaceholderText
        )
        rect = opt.rect.adjusted(14, 8, -14, -8)
        line = opt.fontMetrics.height() + 4
        align = QStyle.visualAlignment(opt.direction, Qt.AlignmentFlag.AlignLeft)
        align |= Qt.AlignmentFlag.AlignVCenter

        painter.save()
        font = opt.font
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(title_color)
        title = opt.fontMetrics.elidedText(
            _rtl(str(index.data(Qt.ItemDataRole.DisplayRole) or "")),
            Qt.TextElideMode.ElideRight,
            rect.width(),
        )
        painter.drawText(QRect(rect.x(), rect.y(), rect.width(), line), align, title)
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        painter.setPen(muted)
        subtitle = opt.fontMetrics.elidedText(
            _rtl(str(index.data(SUBTITLE_ROLE) or "")), Qt.TextElideMode.ElideRight, rect.width()
        )
        painter.drawText(QRect(rect.x(), rect.y() + line, rect.width(), line), align, subtitle)
        painter.restore()


class ListPage(QWidget):
    """Subclasses implement rows(), show_item(), clear_editor(), primary_action(), delete_item()."""

    def __init__(self, title: str, primary_label: str, empty_text: str) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(QLabel(title, objectName="pageTitle"))
        header.addStretch(1)
        self.status = QLabel(objectName="muted")
        header.addWidget(self.status)
        self.primary = QPushButton(primary_label, objectName="primary")
        self.primary.setToolTip("Ctrl+N")
        self.primary.clicked.connect(self.primary_action)
        header.addWidget(self.primary)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(24)
        self.list = QListWidget(objectName="itemList")
        self.list.setFixedWidth(LIST_WIDTH)
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.installEventFilter(self)
        body.addWidget(self.list)

        self.detail = QStackedWidget()
        empty = QLabel(empty_text, objectName="emptyHint")
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.addWidget(empty)
        self.editor = QFrame(objectName="editor")
        self.detail.addWidget(self.editor)
        body.addWidget(self.detail, 1)
        root.addLayout(body, 1)

        self._empty_text = empty_text
        QShortcut(QKeySequence.StandardKey.New, self, activated=self.primary_action)
        self.editor.installEventFilter(self)

    # to implement ------------------------------------------------------------------------
    def rows(self) -> list[Row]:
        raise NotImplementedError

    def show_item(self, item_id: int) -> None:
        raise NotImplementedError

    def clear_editor(self) -> None:
        """Nothing selected."""

    def primary_action(self) -> None:
        raise NotImplementedError

    def delete_item(self, item_id: int) -> None:
        raise NotImplementedError

    def focus_editor(self) -> None:
        self.editor.focusNextChild()

    def focus_main(self) -> None:
        self.list.setFocus()

    # shared behaviour ------------------------------------------------------------------
    def current_id(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else int(item.data(ID_ROLE))

    def refresh(self, select_id: int | None = None, load: bool = True) -> None:
        """Reload the list. With load=False the editor keeps its content (used mid-typing)."""
        keep = select_id if select_id is not None else self.current_id()
        self.list.blockSignals(True)
        self.list.clear()
        target: QListWidgetItem | None = None
        for row in self.rows():
            item = QListWidgetItem(row.title)
            item.setData(ID_ROLE, row.item_id)
            item.setData(SUBTITLE_ROLE, row.subtitle)
            self.list.addItem(item)
            if row.item_id == keep:
                target = item
        self.list.blockSignals(False)
        if target is None and self.list.count():
            target = self.list.item(0)
        if target is not None:
            self.list.blockSignals(not load)
            self.list.setCurrentItem(target)
            self.list.blockSignals(False)
            if load:
                self._on_current_changed(target, None)
        else:
            self.detail.setCurrentIndex(0)
            self.clear_editor()

    def update_row(self, row: Row) -> None:
        """Refresh one list entry in place (after an autosave) without reloading."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if int(item.data(ID_ROLE)) == row.item_id:
                item.setText(row.title)
                item.setData(SUBTITLE_ROLE, row.subtitle)
                return

    def select(self, item_id: int) -> None:
        self.refresh(select_id=item_id)
        self.list.setFocus()

    def _on_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.detail.setCurrentIndex(0)
            self.clear_editor()
            return
        self.detail.setCurrentIndex(1)
        self.show_item(int(current.data(ID_ROLE)))

    def _delete_current(self) -> None:
        item_id = self.current_id()
        if item_id is not None:
            self.delete_item(item_id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if watched is self.list:
                if event.key() == Qt.Key.Key_Delete:
                    self._delete_current()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.current_id():
                    self.focus_editor()
                    return True
            if watched is self.editor and event.key() == Qt.Key.Key_Escape:
                self.list.setFocus()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
