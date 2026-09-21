"""The trash: deleted voices and ideas, restorable for 30 days (`services/trash.py`).

Built like the other list pages (list column, detail pane) but the list takes a
selection of many: restoring or deleting forever works on whatever is selected, and on
everything at once from the buttons under it. The detail pane is a read-only look at
the item, so the user can tell what they are about to restore or lose for good.

The search box here is the only place trashed items are ever found: it matches an
idea's whole text, a voice's file name, and tag names.

Keys: Enter restores the selection, Delete deletes it forever (after asking), Ctrl+A
selects everything shown, Ctrl+F goes to the search box.
"""

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.lifecycle import TRASH_DAYS, TrashKind, days_left
from podcast_workspace.domain.list_filter import ListFilter, parse_list_filter
from podcast_workspace.domain.search import SearchKind
from podcast_workspace.services.trash import TrashItem, TrashKey
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import (
    ID_ROLE,
    LIST_MAX_WIDTH,
    LIST_MIN_WIDTH,
    SUBTITLE_ROLE,
    TwoLineDelegate,
)
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    format_datetime,
    format_duration,
    local_digits,
    show_error,
)

KEY_ROLE = ID_ROLE  # (TrashKind value, item id)
_KINDS: tuple[str, ...] = ("all", TrashKind.VOICE.value, TrashKind.IDEA.value)
_KIND_LABELS = {
    TrashKind.VOICE: SearchKind.VOICE,
    TrashKind.IDEA: SearchKind.IDEA_NOTE,
}


class TrashPage(QWidget):
    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self.nav_title = strings.TRASH_TITLE
        self._ws = workspace
        self._events = events
        self._items: list[TrashItem] = []
        self._filter = ListFilter()
        self._kind = "all"

        body = QHBoxLayout(self)
        body.setContentsMargins(32, 22, 32, 22)
        body.setSpacing(22)

        side_widget = QWidget()
        side_widget.setMinimumWidth(LIST_MIN_WIDTH)
        side_widget.setMaximumWidth(LIST_MAX_WIDTH + 60)
        side = QVBoxLayout(side_widget)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)
        side.addWidget(QLabel(strings.TRASH_TITLE, objectName="pageTitle"))
        hint = QLabel(strings.TRASH_HINT.format(days=local_digits(TRASH_DAYS)), objectName="muted")
        hint.setWordWrap(True)
        side.addWidget(hint)

        self.kinds = QTabBar(objectName="noteTabs")
        self.kinds.setExpanding(False)
        self.kinds.setDocumentMode(True)
        self.kinds.setDrawBase(False)
        for kind in _KINDS:
            self.kinds.addTab(strings.TRASH_KINDS[kind])
        self.kinds.currentChanged.connect(self._on_kind_changed)
        side.addWidget(self.kinds)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter = QLineEdit(objectName="listFilter")
        self.filter.setPlaceholderText(strings.TRASH_FILTER_PLACEHOLDER)
        self.filter.setToolTip(strings.TRASH_FILTER_TOOLTIP)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._on_filter_changed)
        self.filter.installEventFilter(self)
        filter_row.addWidget(self.filter, 1)
        self.filter_count = QLabel(objectName="countPill")
        self.filter_count.hide()
        filter_row.addWidget(self.filter_count)
        side.addLayout(filter_row)

        self.list = QListWidget(objectName="itemList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(lambda _i: self.restore_selected())
        self.list.installEventFilter(self)
        side.addWidget(self.list, 1)

        # What acts on the selection sits right under it; what acts on everything, below.
        selection_row = QHBoxLayout()
        selection_row.setSpacing(8)
        self.restore_button = QPushButton(strings.TRASH_RESTORE, objectName="primary")
        self.restore_button.setToolTip(strings.TRASH_RESTORE_TOOLTIP)
        self.restore_button.clicked.connect(self.restore_selected)
        selection_row.addWidget(self.restore_button)
        self.purge_button = QPushButton(strings.TRASH_PURGE, objectName="danger")
        self.purge_button.setToolTip(strings.TRASH_PURGE_TOOLTIP)
        self.purge_button.clicked.connect(self.purge_selected)
        selection_row.addWidget(self.purge_button)
        selection_row.addStretch(1)
        self.selected_label = QLabel(objectName="muted")
        selection_row.addWidget(self.selected_label)
        side.addLayout(selection_row)

        all_row = QHBoxLayout()
        all_row.setSpacing(8)
        self.select_all_button = QPushButton(strings.TRASH_SELECT_ALL)
        self.select_all_button.setToolTip(strings.TRASH_SELECT_ALL_TOOLTIP)
        self.select_all_button.clicked.connect(self._select_all)
        all_row.addWidget(self.select_all_button)
        all_row.addStretch(1)
        self.restore_all_button = QPushButton(strings.TRASH_RESTORE_ALL)
        self.restore_all_button.clicked.connect(self.restore_all)
        all_row.addWidget(self.restore_all_button)
        self.empty_button = QPushButton(strings.TRASH_EMPTY_ALL, objectName="danger")
        self.empty_button.clicked.connect(self.empty_trash)
        all_row.addWidget(self.empty_button)
        side.addLayout(all_row)
        body.addWidget(side_widget, 3)

        self.detail = QStackedWidget()
        self._empty_label = QLabel(strings.TRASH_EMPTY, objectName="emptyHint")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.addWidget(self._empty_label)
        self.preview = QFrame(objectName="editor")
        col = QVBoxLayout(self.preview)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        self.preview_title = QLabel(objectName="editorTitle")
        self.preview_title.setWordWrap(True)
        col.addWidget(self.preview_title)
        self.preview_meta = QLabel(objectName="muted")
        self.preview_meta.setWordWrap(True)
        col.addWidget(self.preview_meta)
        self.preview_tags = QLabel(objectName="muted")
        self.preview_tags.setWordWrap(True)
        col.addWidget(self.preview_tags)
        self.preview_text = QPlainTextEdit(objectName="ideaText")
        self.preview_text.setReadOnly(True)
        col.addWidget(self.preview_text, 1)
        self.preview_hint = QLabel(objectName="muted")
        self.preview_hint.setWordWrap(True)
        col.addWidget(self.preview_hint)
        col.addStretch(0)
        self.detail.addWidget(self.preview)
        body.addWidget(self.detail, 4)

    # loading ---------------------------------------------------------------------------
    def refresh(self, keep: set[TrashKey] | None = None) -> None:
        """Reload from the database, keeping the selection where the items still exist."""
        if keep is None:
            keep = self.selected_keys()
        try:
            self._items = self._ws.trash.list()
            tag_names = {t.id: t.name for t in self._ws.tags.list_all() if t.id is not None}
        except Exception as exc:
            show_error(self, exc)
            return
        now = datetime.now(UTC)
        of_kind = [i for i in self._items if self._kind in ("all", i.kind.value)]
        shown: list[TrashItem] = []
        for item in of_kind:
            names = [tag_names[t] for t in item.tag_ids if t in tag_names]
            if self._filter.matches(item.text, names):
                shown.append(item)
        self.list.blockSignals(True)
        self.list.clear()
        first_kept: QListWidgetItem | None = None
        for item in shown:
            row = QListWidgetItem(item.title or strings.UNTITLED_NOTE)
            row.setData(KEY_ROLE, (item.kind.value, item.item_id))
            subtitle = self._subtitle(item, now, tag_names)
            row.setData(SUBTITLE_ROLE, subtitle)
            row.setToolTip("\n".join(p for p in (item.title, subtitle) if p))
            self.list.addItem(row)
            if item.key in keep:
                row.setSelected(True)
                first_kept = first_kept or row
        if first_kept is not None:  # the caret moves there; the selection stays as it is
            self.list.setCurrentItem(first_kept, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.list.blockSignals(False)

        filtering = not self._filter.is_empty
        self.filter_count.setVisible(filtering)
        if filtering:
            self.filter_count.setText(
                strings.FILTER_COUNT.format(
                    shown=local_digits(len(shown)), total=local_digits(len(of_kind))
                )
            )
        self._empty_label.setText(
            strings.FILTER_NO_MATCH.format(query=self.filter.text().strip())
            if filtering and of_kind
            else strings.TRASH_EMPTY
        )
        has_any = bool(self._items)
        self.restore_all_button.setEnabled(has_any)
        self.empty_button.setEnabled(has_any)
        self.select_all_button.setEnabled(bool(shown))
        self._on_selection_changed()

    def _subtitle(self, item: TrashItem, now: datetime, tag_names: dict[int, str]) -> str:
        parts = [strings.KIND_LABELS[_KIND_LABELS[item.kind]]]
        left = days_left(item.deleted_at, now)
        parts.append(strings.TRASH_DAYS_LEFT.format(n=local_digits(max(1, left))))
        parts.append(format_datetime(item.deleted_at))
        names = [tag_names[t] for t in item.tag_ids if t in tag_names]
        if names:
            parts.append(strings.LIST_SEPARATOR.join(names))
        return "  ·  ".join(parts)

    @staticmethod
    def _key(row: QListWidgetItem) -> TrashKey:
        kind, item_id = row.data(KEY_ROLE)
        return (TrashKind(kind), int(item_id))

    def selected_keys(self) -> set[TrashKey]:
        return {self._key(row) for row in self.list.selectedItems()}

    def _shown_keys(self) -> list[TrashKey]:
        return [self._key(self.list.item(i)) for i in range(self.list.count())]

    # selection and preview -------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        keys = self.selected_keys()
        n = len(keys)
        self.restore_button.setEnabled(n > 0)
        self.purge_button.setEnabled(n > 0)
        self.selected_label.setText(strings.TRASH_SELECTED.format(n=local_digits(n)) if n else "")
        if n == 0:
            if self.list.count():  # otherwise refresh() has said why the list is empty
                self._empty_label.setText(strings.TRASH_PREVIEW_EMPTY)
            self.detail.setCurrentIndex(0)
            return
        self.detail.setCurrentIndex(1)
        if n > 1:
            self.preview_title.setText(strings.TRASH_SELECTED.format(n=local_digits(n)))
            self.preview_meta.setText(strings.TRASH_PREVIEW_MANY.format(n=local_digits(n)))
            for widget in (self.preview_tags, self.preview_text, self.preview_hint):
                widget.hide()
            return
        (key,) = keys
        item = next((i for i in self._items if i.key == key), None)
        if item is not None:
            self._show_preview(item)

    def _show_preview(self, item: TrashItem) -> None:
        self.preview_title.setText(item.title or strings.UNTITLED_NOTE)
        meta = [strings.KIND_LABELS[_KIND_LABELS[item.kind]]]
        if item.kind is TrashKind.VOICE:
            meta.append(format_duration(item.duration_ms))
        meta.append(strings.TRASH_DELETED_AT.format(when=format_datetime(item.deleted_at)))
        left = days_left(item.deleted_at, datetime.now(UTC))
        meta.append(strings.TRASH_DAYS_LEFT.format(n=local_digits(max(1, left))))
        if item.archived:
            meta.append(strings.TRASH_FROM_ARCHIVE)
        self.preview_meta.setText("  ·  ".join(meta))
        names = [t.name for t in self._ws.tags.by_ids(item.tag_ids)]
        self.preview_tags.setText(strings.LIST_SEPARATOR.join(names))
        self.preview_tags.setVisible(bool(names))
        if item.kind is TrashKind.IDEA:
            self.preview_text.setPlainText(item.text)
            self.preview_text.show()
            self.preview_hint.hide()
        else:
            self.preview_text.setPlainText(item.file_path)
            self.preview_text.setVisible(bool(item.file_path))
            missing = item.file_path and not Path(item.file_path).exists()
            self.preview_hint.setText(
                strings.VOICE_MISSING if missing else strings.TRASH_VOICE_HINT
            )
            self.preview_hint.show()

    def _select_all(self) -> None:
        self.list.selectAll()
        self.list.setFocus()

    # actions ---------------------------------------------------------------------------
    def restore_selected(self) -> None:
        self._restore(self.selected_keys())

    def restore_all(self) -> None:
        keys = [i.key for i in self._items]
        if not keys:
            return
        text = strings.TRASH_RESTORE_ALL_CONFIRM.format(n=local_digits(len(keys)))
        if confirm(self, text, strings.TRASH_RESTORE_ALL):
            self._restore(keys)

    def _restore(self, keys: set[TrashKey] | list[TrashKey]) -> None:
        if not keys:
            return
        row = self._first_selected_row()
        try:
            n = self._ws.trash.restore(keys)
        except Exception as exc:
            show_error(self, exc)
            return
        self._after_change(strings.TRASH_RESTORED.format(n=local_digits(n)), row)

    def purge_selected(self) -> None:
        keys = self.selected_keys()
        if not keys:
            return
        text = strings.TRASH_PURGE_CONFIRM.format(n=local_digits(len(keys)))
        if confirm(self, text, strings.TRASH_PURGE):
            self._purge(keys)

    def empty_trash(self) -> None:
        keys = [i.key for i in self._items]
        if not keys:
            return
        text = strings.TRASH_EMPTY_CONFIRM.format(n=local_digits(len(keys)))
        if confirm(self, text, strings.TRASH_EMPTY_ALL):
            self._purge(keys)

    def _purge(self, keys: set[TrashKey] | list[TrashKey]) -> None:
        row = self._first_selected_row()
        try:
            report = self._ws.trash.purge(keys)
        except Exception as exc:
            show_error(self, exc)
            return
        self._after_change(strings.TRASH_PURGED.format(n=local_digits(len(report))), row)

    def _first_selected_row(self) -> int:
        rows = [self.list.row(item) for item in self.list.selectedItems()]
        return min(rows) if rows else 0

    def _after_change(self, message: str, row: int) -> None:
        """Reload, then land on the row that took the place of what left."""
        self._events.data_changed.emit()
        self.refresh(keep=set())
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))
        self.list.setFocus()
        self.status_message(message)

    def status_message(self, message: str) -> None:
        self.selected_label.setText(message)
        QTimer.singleShot(5000, self._on_selection_changed)

    # filtering, kinds ------------------------------------------------------------------
    def _on_filter_changed(self, text: str) -> None:
        self._filter = parse_list_filter(text)
        self.refresh()

    def _on_kind_changed(self, index: int) -> None:
        self._kind = _KINDS[max(0, index)]
        self.refresh()

    def focus_main(self) -> None:
        self.list.setFocus()

    def focus_filter(self) -> None:
        self.filter.setFocus()
        self.filter.selectAll()

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> dict[str, object]:
        return {
            "filter": self.filter.text(),
            "kind": self._kind,
            "selected": self.selected_keys(),
            "scroll": self.list.verticalScrollBar().value(),
        }

    def restore_nav_state(self, state: object) -> None:
        if not isinstance(state, dict):
            return
        self._kind = str(state.get("kind", "all"))
        self.kinds.blockSignals(True)
        self.kinds.setCurrentIndex(_KINDS.index(self._kind) if self._kind in _KINDS else 0)
        self.kinds.blockSignals(False)
        self.filter.blockSignals(True)
        self.filter.setText(str(state.get("filter", "")))
        self.filter.blockSignals(False)
        self._filter = parse_list_filter(self.filter.text())
        selected = state.get("selected")
        self.refresh(keep=selected if isinstance(selected, set) else set())
        scroll = state.get("scroll")
        if isinstance(scroll, int):
            self.list.verticalScrollBar().setValue(scroll)

    # keys and lifecycle ----------------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if watched is self.list:
                if event.key() == Qt.Key.Key_Delete:
                    self.purge_selected()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.restore_selected()
                    return True
            if watched is self.filter:
                if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.list.setFocus()
                    if self.list.currentItem() is None and self.list.count():
                        self.list.setCurrentRow(0)
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    if self.filter.text():
                        self.filter.clear()
                    else:
                        self.list.setFocus()
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
