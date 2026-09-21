"""Master/detail page skeleton shared by Episodes, Voices and Ideas.

Layout (RTL): [[title .... primary button] [filter] list | editor], the detail pane
running the full height of the page.
Keys: Ctrl+N primary action, Ctrl+F the filter box, Delete deletes the selected item
(list focused), Enter in the list moves focus into the editor, Esc in the editor returns
to the list.

The filter box narrows this page's own list by title and tag (`domain/list_filter.py`),
which is a different job from the sidebar's global search: it takes rows away from what
is already in front of you instead of opening a page of hits from everywhere. A page
asks for one by passing `filter_placeholder`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QKeyEvent, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.list_filter import ListFilter, parse_list_filter
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import direction_mark, local_digits
from podcast_workspace.ui.theme import TEXT_WEIGHT


def _rtl(text: str) -> str:
    # A direction mark in front fixes the base direction of mixed Persian/Latin/digit
    # text; around separators it stops Persian digits after a Latin word (e.g.
    # "WAV · ۲۸") from joining the Latin run (Unicode bidi rule W7). The mark follows
    # the UI language: RLM in Persian, LRM in English.
    mark = strings.DIRECTION_MARK
    return mark + text.replace("·", f"{mark}·{mark}")


def _own_direction(text: str) -> str:
    """A title (a name the user typed, a file name) keeps the direction of its own script."""
    return direction_mark(text) + text


ID_ROLE = Qt.ItemDataRole.UserRole
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
# The list breathes with the window instead of staying at one width: wide enough for
# Persian titles on a large screen, still readable at the minimum window size.
LIST_MIN_WIDTH = 288
LIST_MAX_WIDTH = 440


@dataclass(frozen=True)
class Row:
    """One list entry. `tags` is what the filter box matches besides the title; it is
    empty on pages that carry no tags."""

    item_id: int
    title: str
    subtitle: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListPageState:
    """What this page looked like when the user navigated away from it."""

    filter_text: str = ""
    current_id: int | None = None
    scroll: int = 0
    extra: dict[str, object] = field(default_factory=dict)


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

        # The selection is a soft tint (theme accent_soft), so text keeps its own colours.
        palette = opt.palette
        title_color = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
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
            _own_direction(str(index.data(Qt.ItemDataRole.DisplayRole) or "")),
            Qt.TextElideMode.ElideRight,
            rect.width(),
        )
        painter.drawText(QRect(rect.x(), rect.y(), rect.width(), line), align, title)
        font.setWeight(TEXT_WEIGHT)
        painter.setFont(font)
        painter.setPen(muted)
        subtitle = opt.fontMetrics.elidedText(
            _rtl(str(index.data(SUBTITLE_ROLE) or "")), Qt.TextElideMode.ElideRight, rect.width()
        )
        painter.drawText(QRect(rect.x(), rect.y() + line, rect.width(), line), align, subtitle)
        painter.restore()


class _StatusLabel(QLabel):
    """A passing message under the page title ("3 files imported"): takes no room while
    there is nothing to say."""

    def __init__(self) -> None:
        super().__init__(objectName="muted")
        self.setWordWrap(True)
        self.hide()

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        self.setVisible(bool(text))


class ListPage(QWidget):
    """Subclasses implement rows(), show_item(), clear_editor(), primary_action(), delete_item()."""

    def __init__(
        self,
        title: str,
        primary_label: str,
        empty_text: str,
        list_weight: int = 2,
        detail_weight: int = 5,
        filter_placeholder: str = "",
    ) -> None:
        super().__init__()
        self.nav_title = title
        self._filter = ListFilter()
        self._total_rows = 0
        # Three panes, each with its own head: the list column carries the page's name,
        # its "new" button and its filter, and the detail pane gets the full height.
        body = QHBoxLayout(self)
        body.setContentsMargins(32, 22, 32, 22)
        body.setSpacing(22)
        self.list = QListWidget(objectName="itemList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.installEventFilter(self)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)

        # The filter belongs to the list, so it sits in the same column and carries the
        # same width limits; the column, not the list, is what the layout stretches.
        list_side = self.list_side = QWidget()
        list_side.setMinimumWidth(LIST_MIN_WIDTH)
        list_side.setMaximumWidth(LIST_MAX_WIDTH)
        side = QVBoxLayout(list_side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(QLabel(title, objectName="pageTitle"))
        header.addStretch(1)
        self.primary = QPushButton(primary_label, objectName="primary")
        self.primary.setToolTip("Ctrl+N")
        self.primary.clicked.connect(self.primary_action)
        header.addWidget(self.primary)
        side.addLayout(header)
        self.status = _StatusLabel()
        side.addWidget(self.status)

        self.filter: QLineEdit | None = None
        self.filter_count = QLabel(objectName="countPill")
        self.filter_count.hide()
        if filter_placeholder:
            filter_row = QHBoxLayout()
            filter_row.setSpacing(8)
            self.filter = QLineEdit(objectName="listFilter")
            self.filter.setPlaceholderText(filter_placeholder)
            self.filter.setToolTip(strings.FILTER_TOOLTIP)
            self.filter.setClearButtonEnabled(True)
            self.filter.textChanged.connect(self._on_filter_changed)
            self.filter.installEventFilter(self)
            filter_row.addWidget(self.filter, 1)
            # The count is the promise that nothing was lost, only hidden.
            filter_row.addWidget(self.filter_count)
            side.addLayout(filter_row)
        side.addWidget(self.list, 1)
        body.addWidget(list_side, list_weight)

        self.detail = QStackedWidget()
        self._empty_label = QLabel(empty_text, objectName="emptyHint")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.addWidget(self._empty_label)
        self.editor = QFrame(objectName="editor")
        self.detail.addWidget(self.editor)
        body.addWidget(self.detail, detail_weight)

        self._empty_text = empty_text
        QShortcut(QKeySequence.StandardKey.New, self, activated=self.new_shortcut)
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

    def row_actions(self, item_id: int) -> list[tuple[str, Callable[[], None]]]:
        """What a right-click on a row offers; nothing by default (no menu at all)."""
        return []

    def new_shortcut(self) -> None:
        """Ctrl+N. A page whose detail pane makes things of its own routes it by focus."""
        self.primary_action()

    def focus_editor(self) -> None:
        self.editor.focusNextChild()

    def focus_main(self) -> None:
        self.list.setFocus()

    def focus_filter(self) -> None:
        """Ctrl+F. Pages without a filter box put the caret where typing helps instead."""
        if self.filter is None:
            self.focus_main()
            return
        self.filter.setFocus()
        self.filter.selectAll()

    # filtering -------------------------------------------------------------------------
    def filter_text(self) -> str:
        return self.filter.text() if self.filter is not None else ""

    def set_filter_text(self, text: str) -> None:
        """Set the box without a reload; the caller refreshes once, afterwards."""
        if self.filter is None or self.filter.text() == text:
            return
        self.filter.blockSignals(True)
        self.filter.setText(text)
        self.filter.blockSignals(False)
        self._filter = parse_list_filter(text)

    def clear_filter(self, reload: bool = True) -> None:
        """Empty the box. An item the filter hides is an item the user was sent to, or
        just made, and cannot see — so jumping and creating both come through here.

        `reload=False` is for callers that are about to refresh anyway.
        """
        if self.filter is None or not self.filter.text():
            return
        self.set_filter_text("")
        if reload:
            self.refresh()

    def _on_filter_changed(self, text: str) -> None:
        self._filter = parse_list_filter(text)
        self.refresh()

    def _update_filter_count(self, shown: int, total: int) -> None:
        """Say how much is hidden, and only then — a pill on an unfiltered list is noise."""
        filtering = not self._filter.is_empty
        self.filter_count.setVisible(filtering)
        if filtering:
            text = strings.FILTER_COUNT.format(shown=local_digits(shown), total=local_digits(total))
            self.filter_count.setText(text)
            self.filter_count.setToolTip(
                strings.FILTER_COUNT_TOOLTIP.format(
                    shown=local_digits(shown), total=local_digits(total)
                )
            )
        self._empty_label.setText(
            strings.FILTER_NO_MATCH.format(query=self.filter_text().strip())
            if filtering and not shown and total
            else self._empty_text
        )

    # shared behaviour ------------------------------------------------------------------
    def current_id(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else int(item.data(ID_ROLE))

    def refresh(self, select_id: int | None = None, load: bool = True) -> None:
        """Reload the list. With load=False the editor keeps its content (used mid-typing).

        `select_id` also pins that row past the filter: a row the caller just created or
        was sent to must not vanish under a filter box it happens not to match.
        """
        keep = select_id if select_id is not None else self.current_id()
        rows = self.rows()
        self._total_rows = len(rows)
        shown = [r for r in rows if r.item_id == select_id or self._filter.matches(r.title, r.tags)]
        self._update_filter_count(len(shown), len(rows))
        self.list.blockSignals(True)
        self.list.clear()
        target: QListWidgetItem | None = None
        for row in shown:
            item = QListWidgetItem(row.title)
            item.setData(ID_ROLE, row.item_id)
            item.setData(SUBTITLE_ROLE, row.subtitle)
            # Both lines are elided to the list's width; the tooltip is where the rest is.
            item.setToolTip("\n".join(part for part in (row.title, row.subtitle) if part))
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
                item.setToolTip("\n".join(part for part in (row.title, row.subtitle) if part))
                return

    def select(self, item_id: int) -> None:
        self.clear_filter(reload=False)
        self.refresh(select_id=item_id)
        self.list.setFocus()

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> ListPageState:
        return ListPageState(
            filter_text=self.filter_text(),
            current_id=self.current_id(),
            scroll=self.list.verticalScrollBar().value(),
        )

    def restore_nav_state(self, state: object) -> None:
        if not isinstance(state, ListPageState):
            return
        self.set_filter_text(state.filter_text)
        self.refresh(select_id=state.current_id)
        self.list.verticalScrollBar().setValue(state.scroll)

    def _on_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.detail.setCurrentIndex(0)
            self.clear_editor()
            return
        self.detail.setCurrentIndex(1)
        self.show_item(int(current.data(ID_ROLE)))

    def _row_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.list.setCurrentItem(item)
        actions = self.row_actions(int(item.data(ID_ROLE)))
        if not actions:
            return
        menu = QMenu(self.list)
        for label, callback in actions:
            menu.addAction(label, callback)
        menu.exec(self.list.viewport().mapToGlobal(pos))

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
            # A hidden list (Episodes, with the list pane put away) cannot take focus back.
            if (
                watched is self.editor
                and event.key() == Qt.Key.Key_Escape
                and self.list.isVisible()
            ):
                self.list.setFocus()
                return True
            if watched is self.filter:
                # Down/Enter walk into the results; Esc empties the box, and only once it
                # is empty does it hand the page back.
                if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.focus_main()
                    return True
                if event.key() == Qt.Key.Key_Escape and self.filter is not None:
                    if self.filter.text():
                        self.filter.clear()
                    else:
                        self.focus_main()
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
