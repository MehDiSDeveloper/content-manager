"""Kanban board: one column per pipeline status, episode cards, drag & drop or keys to move.

Keys: ←/→ move between columns, ↑/↓ within one, Ctrl+←/→ moves the card one column in that
visual direction, Enter opens the episode workspace, Ctrl+N creates an episode.
Columns follow the pipeline in reading order, so in RTL the first status is on the right.
"""

from datetime import UTC, datetime

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPalette,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Episode, EpisodeStatus
from podcast_workspace.domain.pipeline import PIPELINE, days_untouched, is_stale
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import AppEvents, local_digits, show_error
from podcast_workspace.ui.theme import TEXT_WEIGHT, colors

ID_ROLE = Qt.ItemDataRole.UserRole
NEXT_ROLE = Qt.ItemDataRole.UserRole + 1
STALE_ROLE = Qt.ItemDataRole.UserRole + 2
COLUMN_WIDTH = 150


class _CardDelegate(QStyledItemDelegate):
    """Card: stale badge, title (wrapped, up to 2 lines), next action (muted, 2 lines)."""

    TITLE_LINES = 2

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        line = option.fontMetrics.height()
        extra = line + 6 if index.data(STALE_ROLE) else 0
        title_lines = self._title_lines(option, index)
        has_next = bool(index.data(NEXT_ROLE))
        body = line * 2 + 2 if has_next else 0
        return QSize(option.rect.width(), line * title_lines + body + 34 + extra)

    def _title_lines(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> int:
        """Columns are narrow; let a long Persian title use a second line instead of
        eliding it to three words."""
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        width = max(40, option.rect.width() - 28)
        needed = option.fontMetrics.horizontalAdvance(title)
        return min(self.TITLE_LINES, max(1, -(-needed // width)))

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # The column's own palette is transparent (stylesheet); cards use the app's colours.
        palette = QApplication.palette()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        focused = bool(opt.state & QStyle.StateFlag.State_HasFocus)
        widget_focused = opt.widget is not None and opt.widget.hasFocus()
        rect = opt.rect.adjusted(2, 3, -2, -3)
        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A soft shadow lifts the card off its tinted column.
        shadow = QColor(colors().text)
        shadow.setAlphaF(0.07 if hovered else 0.04)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(rect.translated(0, 2), 10, 10)
        chosen = selected and widget_focused
        border = palette.color(QPalette.ColorRole.Link if chosen else QPalette.ColorRole.Mid)
        if hovered and not chosen:
            border = palette.color(QPalette.ColorRole.Highlight)
        painter.setPen(border)
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(rect, 10, 10)
        if chosen and focused:
            painter.setPen(palette.color(QPalette.ColorRole.Link))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 9, 9)

        inner = rect.adjusted(12, 10, -12, -10)
        metrics = opt.fontMetrics
        line = metrics.height()
        align = QStyle.visualAlignment(opt.direction, Qt.AlignmentFlag.AlignLeft)
        y = inner.y()
        stale = index.data(STALE_ROLE)
        if stale:
            badge_font = QFont(opt.font)  # a copy: the title must keep its size
            badge_font.setPointSizeF(max(7.5, badge_font.pointSizeF() - 1.5))
            painter.setFont(badge_font)
            painter.setPen(QColor(colors().warning))
            painter.drawText(
                QRect(inner.x(), y, inner.width(), line), align, strings.DIRECTION_MARK + stale
            )
            y += line + 6
        font = opt.font
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        title_lines = self._title_lines(opt, index)
        title_box = QRect(inner.x(), y, inner.width(), line * title_lines + 2)
        painter.drawText(
            title_box,
            int(align | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            strings.DIRECTION_MARK + _clip(str(index.data(Qt.ItemDataRole.DisplayRole) or ""), 70),
        )
        y += line * title_lines + 6
        font.setWeight(TEXT_WEIGHT)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        next_action = str(index.data(NEXT_ROLE) or "")
        if next_action:
            box = QRect(inner.x(), y, inner.width(), line * 2 + 2)
            flags = align | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
            painter.drawText(box, int(flags), strings.DIRECTION_MARK + _clip(next_action))
        painter.restore()


def _clip(text: str, limit: int = 90) -> str:
    """Keep the next action within the card's two wrapped lines."""
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


class _Column(QListWidget):
    moved = Signal(int, object)  # episode_id, EpisodeStatus
    open_card = Signal(int)
    step = Signal(object, int)  # column status, visual direction (-1 left, +1 right)
    move_card = Signal(int, int)  # episode_id, visual direction

    def __init__(self, status: EpisodeStatus) -> None:
        super().__init__(objectName="boardColumn")
        self.status = status
        self.setItemDelegate(_CardDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSpacing(2)
        self.setMouseTracking(True)  # cards lift on hover
        self.itemDoubleClicked.connect(lambda item: self.open_card.emit(int(item.data(ID_ROLE))))

    def current_id(self) -> int | None:
        item = self.currentItem()
        return None if item is None else int(item.data(ID_ROLE))

    def sizeHint(self) -> QSize:
        return QSize(COLUMN_WIDTH, 400)  # QListWidget's default hint (256 px) forces scrolling

    def minimumSizeHint(self) -> QSize:
        return QSize(COLUMN_WIDTH - 20, 120)

    # drag & drop: the board reloads from the database, so Qt never moves items itself
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if isinstance(event.source(), _Column):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if isinstance(event.source(), _Column):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        source = event.source()
        if not isinstance(source, _Column):
            event.ignore()
            return
        episode_id = source.current_id()
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if episode_id is not None and source is not self:
            # After the drag's own event loop unwinds: the move reloads (clears) the columns.
            status = self.status
            QTimer.singleShot(0, lambda: self.moved.emit(episode_id, status))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            direction = -1 if key == Qt.Key.Key_Left else 1
            if ctrl:
                card = self.current_id()
                if card is not None:
                    self.move_card.emit(card, direction)
            else:
                self.step.emit(self.status, direction)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            card = self.current_id()
            if card is not None:
                self.open_card.emit(card)
            return
        super().keyPressEvent(event)


class BoardPage(QWidget):
    open_episode = Signal(int)

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self.nav_title = strings.BOARD_TITLE
        self._ws = workspace
        self._events = events
        self._episodes: dict[int, Episode] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(strings.BOARD_TITLE, objectName="pageTitle")
        title.setToolTip(strings.BOARD_HINT)
        header.addWidget(title)
        header.addStretch(1)
        self.primary = QPushButton(strings.EPISODE_NEW, objectName="primary")
        self.primary.setToolTip("Ctrl+N")
        self.primary.clicked.connect(self.primary_action)
        header.addWidget(self.primary)
        root.addLayout(header)

        host = QWidget(objectName="boardHost")
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.columns: list[_Column] = []
        self._counts: list[QLabel] = []
        for status in PIPELINE:
            frame = QFrame(objectName="boardFrame")
            frame.setProperty("status", status.value)  # its pastel: theme.STATUS_INKS
            frame.setMinimumWidth(COLUMN_WIDTH)
            col = QVBoxLayout(frame)
            col.setContentsMargins(8, 12, 8, 8)
            col.setSpacing(8)
            head = QHBoxLayout()
            head.setContentsMargins(6, 0, 6, 0)
            head.setSpacing(8)
            dot = QLabel(objectName="statusDot")
            dot.setProperty("status", status.value)
            head.addWidget(dot)
            head.addWidget(QLabel(strings.STATUS_LABELS[status], objectName="columnTitle"))
            head.addStretch(1)
            count = QLabel(objectName="countPill")
            head.addWidget(count)
            col.addLayout(head)
            column = _Column(status)
            column.moved.connect(self._move)
            column.open_card.connect(self.open_episode.emit)
            column.step.connect(self._step_focus)
            column.move_card.connect(self._move_visual)
            col.addWidget(column, 1)
            row.addWidget(frame, 1)
            self.columns.append(column)
            self._counts.append(count)
        self.scroll = QScrollArea(objectName="boardScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)
        # Six empty columns say nothing; one sentence does.
        self.empty = QLabel(strings.BOARD_EMPTY, objectName="emptyHint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.hide()
        root.addWidget(self.empty, 1)
        QShortcut(QKeySequence.StandardKey.New, self, activated=self.primary_action)

    # data -------------------------------------------------------------------------------
    def refresh(self, focus_id: int | None = None) -> None:
        try:
            episodes = self._ws.episodes.list_all()
        except Exception as exc:
            show_error(self, exc)
            return
        now = datetime.now(UTC)
        self._episodes = {e.id: e for e in episodes if e.id is not None}
        self.empty.setVisible(not episodes)
        self.scroll.setVisible(bool(episodes))
        keep = focus_id
        if keep is None:
            focused = QApplication.focusWidget()
            if isinstance(focused, _Column):
                keep = focused.current_id()
        target: tuple[_Column, QListWidgetItem] | None = None
        for column, count in zip(self.columns, self._counts, strict=True):
            column.clear()
            cards = [e for e in episodes if e.status is column.status]
            count.setText(local_digits(len(cards)) if cards else "")
            for episode in cards:  # list_all is newest-updated first
                item = QListWidgetItem(episode.title)
                item.setData(ID_ROLE, episode.id)
                item.setData(NEXT_ROLE, episode.next_action)
                stale = ""
                if is_stale(episode, now):
                    stale = strings.STALE_BADGE.format(
                        days=local_digits(days_untouched(episode, now))
                    )
                item.setData(STALE_ROLE, stale)
                if stale:
                    item.setToolTip(strings.STALE_TOOLTIP)
                column.addItem(item)
                if episode.id == keep:
                    target = (column, item)
        if target is not None:
            column, item = target
            column.setCurrentItem(item)
            if focus_id is not None or self.isVisible():
                column.setFocus()

    # navigation state -------------------------------------------------------------------
    def nav_state(self) -> tuple[int | None, int]:
        """The card in hand and how far the board is scrolled sideways."""
        focused = QApplication.focusWidget()
        current = focused.current_id() if isinstance(focused, _Column) else None
        if current is None:
            current = next(
                (c.current_id() for c in self.columns if c.currentItem() is not None), None
            )
        return current, self.scroll.horizontalScrollBar().value()

    def restore_nav_state(self, state: object) -> None:
        if not isinstance(state, tuple) or len(state) != 2:
            return
        episode_id, scroll = state
        self.refresh(focus_id=episode_id if isinstance(episode_id, int) else None)
        self.scroll.horizontalScrollBar().setValue(int(scroll))

    def focus_main(self) -> None:
        for column in self.columns:
            if column.count():
                column.setFocus()
                if column.currentItem() is None:
                    column.setCurrentRow(0)
                return
        self.primary.setFocus()

    def primary_action(self) -> None:
        try:
            episode = self._ws.episodes.create(strings.EPISODE_DEFAULT_TITLE)
        except Exception as exc:
            show_error(self, exc)
            return
        self._events.data_changed.emit()
        assert episode.id is not None
        self.open_episode.emit(episode.id)

    # moves ------------------------------------------------------------------------------
    def _move(self, episode_id: int, status: EpisodeStatus) -> None:
        try:
            self._ws.episodes.set_status(episode_id, status)
        except Exception as exc:
            show_error(self, exc)
            return
        self._events.data_changed.emit()
        self.refresh(focus_id=episode_id)

    def _visual_step(self, status: EpisodeStatus, direction: int) -> EpisodeStatus | None:
        # Visual "left" is the next status in RTL, the previous one in LTR.
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        step = -direction if rtl else direction
        index = PIPELINE.index(status) + step
        return PIPELINE[index] if 0 <= index < len(PIPELINE) else None

    def _move_visual(self, episode_id: int, direction: int) -> None:
        episode = self._episodes.get(episode_id)
        if episode is None:
            return
        target = self._visual_step(episode.status, direction)
        if target is not None:
            self._move(episode_id, target)

    def _step_focus(self, status: EpisodeStatus, direction: int) -> None:
        target = self._visual_step(status, direction)
        while target is not None:
            column = self.columns[PIPELINE.index(target)]
            if column.count():
                column.setFocus()
                if column.currentItem() is None:
                    column.setCurrentRow(0)
                return
            target = self._visual_step(target, direction)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
