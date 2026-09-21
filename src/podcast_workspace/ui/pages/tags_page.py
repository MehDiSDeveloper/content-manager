"""Tag manager: create, rename (F2), recolor, merge, delete. Tags are flat.

Layout (RTL): filter + tag list on the right, and on the left the items that carry the
selected tag — a tag is only worth having if you can see what it gathers, and from here
you can jump straight to any of them. Jumping is a one-way door without a way home, so
the page hands its whole standing — filter text, selected tag, the row of the uses list,
both scroll positions — to `ui/navigation.py` on the way out.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.search import SearchKind
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import SUBTITLE_ROLE, TwoLineDelegate
from podcast_workspace.ui.support import AppEvents, confirm, local_digits, show_error
from podcast_workspace.ui.widgets.key_hint import add_key_hint, attach_key_hint
from podcast_workspace.ui.widgets.tag_dialogs import NewTagDialog, TagPickerDialog
from podcast_workspace.ui.widgets.tag_widgets import color_dot

ID_ROLE = Qt.ItemDataRole.UserRole
# Qt stores item data as a QVariant, which hands a Python enum back as the plain str or
# int behind it — so what goes in here is the SearchKind's number, and what comes out is
# put back through SearchKind(). Never compare the raw value with `is`.
KIND_ROLE = Qt.ItemDataRole.UserRole + 3
LIST_WIDTH = 460
USES_LIMIT = 200


@dataclass(frozen=True)
class TagsPageState:
    """What this page looked like when the user navigated away from it."""

    filter_text: str = ""
    tag_id: int | None = None
    uses_row: int = -1
    list_scroll: int = 0
    uses_scroll: int = 0


class TagsPage(QWidget):
    open_episode = Signal(int)
    open_voice = Signal(int)
    open_idea = Signal(int)

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self.nav_title = strings.TAGS_TITLE
        self._ws = workspace
        self._events = events
        self._items: dict[int, QTreeWidgetItem] = {}
        self._filling = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 22, 32, 22)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(QLabel(strings.TAGS_TITLE, objectName="pageTitle"))
        header.addStretch(1)
        self.primary = QPushButton(strings.TAG_NEW, objectName="primary")
        self.primary.clicked.connect(lambda: self.create_tag())
        header.addWidget(self.primary)
        # Ctrl+N works here too, but Ctrl+T works everywhere: that is the one to learn.
        add_key_hint(header, self.primary, "Ctrl+T")
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(22)

        left = QVBoxLayout()
        left.setSpacing(10)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter = QLineEdit(placeholderText=strings.TAG_FILTER_PLACEHOLDER)
        self.filter.setToolTip(strings.TAG_FILTER_TOOLTIP)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.filter.installEventFilter(self)
        attach_key_hint(self.filter, "Ctrl+F")
        filter_row.addWidget(self.filter, 1)
        # Six verbs in a row taught nothing; one menu (and the right-click menu on the
        # row itself) keeps the same actions where the tag is.
        self.actions_button = QToolButton(objectName="chromeButton")
        self.actions_button.setText(strings.TAG_ACTIONS + "  ⌄")
        self.actions_button.setToolTip(strings.TAG_ACTIONS_TOOLTIP)
        self.actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.actions_menu = QMenu(self.actions_button)
        self.actions_button.setMenu(self.actions_menu)
        filter_row.addWidget(self.actions_button)
        left.addLayout(filter_row)

        # A two-column list (name, usage); QTreeWidget is Qt's multi-column list view.
        self.tag_list = QTreeWidget(objectName="tagList")
        self.tag_list.setRootIsDecorated(False)
        self.tag_list.setColumnCount(2)
        self.tag_list.setHeaderLabels([strings.TAG_NAME_HEADER, strings.TAG_USAGE_HEADER])
        self.tag_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tag_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tag_list.header().setStretchLastSection(False)
        self.tag_list.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)  # F2
        self.tag_list.itemChanged.connect(self._on_item_changed)
        self.tag_list.currentItemChanged.connect(lambda *_: self._on_selection_changed())
        self.tag_list.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.tag_list.installEventFilter(self)
        left.addWidget(self.tag_list, 1)

        self.empty = QLabel(strings.TAG_EMPTY, objectName="emptyHint")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.empty)
        list_side = QWidget()
        list_side.setLayout(left)
        list_side.setMaximumWidth(LIST_WIDTH)
        body.addWidget(list_side, 2)

        uses = QVBoxLayout()
        uses.setSpacing(10)
        uses_head = QHBoxLayout()
        uses_head.setSpacing(8)
        self.uses_title = QLabel(strings.TAG_USES_TITLE, objectName="sectionTitle")
        uses_head.addWidget(self.uses_title)
        self.uses_count = QLabel(objectName="countPill")
        uses_head.addWidget(self.uses_count)
        uses_head.addStretch(1)
        uses.addLayout(uses_head)
        self.uses = QListWidget(objectName="usesList")
        self.uses.setItemDelegate(TwoLineDelegate(self.uses))
        self.uses.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.uses.setToolTip(strings.TAG_OPEN_ITEM)
        self.uses.itemActivated.connect(self._open_use)
        self.uses.itemDoubleClicked.connect(self._open_use)
        uses.addWidget(self.uses, 1)
        self.uses_hint = QLabel(objectName="muted")
        self.uses_hint.setWordWrap(True)
        uses.addWidget(self.uses_hint)
        body.addLayout(uses, 3)
        root.addLayout(body, 1)

        self._actions: list[QAction] = []
        for label, shortcut, handler in (
            (strings.TAG_RENAME, "F2", self.rename_tag),
            (strings.TAG_RECOLOR, "Ctrl+Shift+C", self.recolor_tag),
            (strings.TAG_MERGE, "Ctrl+Shift+M", self.merge_tag),
            (strings.TAG_DELETE, "Del", self.delete_tag),
        ):
            action = QAction(label, self.tag_list)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(handler)
            self.tag_list.addAction(action)
            self.actions_menu.addAction(action)
            self._actions.append(action)

        new_action = QAction(self, shortcut=QKeySequence.StandardKey.New)
        new_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        new_action.triggered.connect(lambda: self.create_tag())
        self.addAction(new_action)
        events.tags_changed.connect(self.refresh)

    # data ------------------------------------------------------------------------------
    def refresh(self, select_id: int | None = None) -> None:
        keep = select_id if select_id is not None else self.current_id()
        tags = self._ws.tags.list_all()
        usage = self._ws.tags.usage_counts()
        self._filling = True
        self.tag_list.clear()
        self._items = {}
        for tag in tags:
            assert tag.id is not None
            item = QTreeWidgetItem([tag.name, local_digits(usage.get(tag.id, 0))])
            item.setIcon(0, color_dot(tag.color))
            item.setData(0, ID_ROLE, tag.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
            self._items[tag.id] = item
            self.tag_list.addTopLevelItem(item)
        self.tag_list.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._filling = False
        self.tag_list.setVisible(bool(tags))
        self.empty.setVisible(not tags)
        target = self._items.get(keep) if keep is not None else None
        if target is None and self.tag_list.topLevelItemCount():
            target = self.tag_list.topLevelItem(0)
        if target is not None:
            self.tag_list.setCurrentItem(target)
        self._apply_filter(self.filter.text())
        self._on_selection_changed()

    def current_id(self) -> int | None:
        item = self.tag_list.currentItem()
        return None if item is None else int(item.data(0, ID_ROLE))

    def current_tag(self) -> Tag | None:
        tag_id = self.current_id()
        return self._ws.tags.get(tag_id) if tag_id is not None else None

    def focus_main(self) -> None:
        self.tag_list.setFocus()

    def focus_filter(self) -> None:
        """Ctrl+F, same as the filter box on the list pages."""
        self.filter.setFocus()
        self.filter.selectAll()

    def select(self, tag_id: int) -> None:
        self.filter.clear()
        self.refresh(select_id=tag_id)
        self.tag_list.setFocus()

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> TagsPageState:
        return TagsPageState(
            filter_text=self.filter.text(),
            tag_id=self.current_id(),
            uses_row=self.uses.currentRow(),
            list_scroll=self.tag_list.verticalScrollBar().value(),
            uses_scroll=self.uses.verticalScrollBar().value(),
        )

    def restore_nav_state(self, state: object) -> None:
        if not isinstance(state, TagsPageState):
            return
        self.filter.blockSignals(True)
        self.filter.setText(state.filter_text)
        self.filter.blockSignals(False)
        self.refresh(select_id=state.tag_id)  # also reruns the filter and the uses list
        self.tag_list.verticalScrollBar().setValue(state.list_scroll)
        if 0 <= state.uses_row < self.uses.count():
            self.uses.setCurrentRow(state.uses_row)
        self.uses.verticalScrollBar().setValue(state.uses_scroll)

    def _update_actions(self) -> None:
        tag = self.current_tag()
        for action in self._actions:
            action.setEnabled(tag is not None)
        self.actions_button.setEnabled(tag is not None)

    def _on_selection_changed(self) -> None:
        self._update_actions()
        self._show_uses()

    def _show_uses(self) -> None:
        """Everything carrying the selected tag, newest first, ready to open."""
        self.uses.clear()
        tag = self.current_tag()
        if tag is None or tag.id is None:
            self.uses_count.setText("")
            self.uses_count.hide()
            self.uses_hint.setText(strings.TAG_USES_NONE)
            self.uses_hint.show()
            return
        tag_id = tag.id
        rows: list[tuple[SearchKind, int, str, str]] = []
        try:
            for episode in self._ws.episodes.list_all():
                if tag_id in episode.tag_ids and episode.id is not None:
                    rows.append(
                        (
                            SearchKind.EPISODE,
                            episode.id,
                            episode.title,
                            strings.KIND_LABELS[SearchKind.EPISODE]
                            + "  ·  "
                            + strings.STATUS_LABELS[episode.status],
                        )
                    )
            for voice in self._ws.voices.list_all():
                if tag_id in voice.tag_ids and voice.id is not None:
                    rows.append(
                        (
                            SearchKind.VOICE,
                            voice.id,
                            Path(voice.file_path).name,
                            strings.KIND_LABELS[SearchKind.VOICE] + "  ·  " + voice.format.upper(),
                        )
                    )
            for idea in self._ws.ideas.list_all():
                if tag_id in idea.tag_ids and idea.id is not None:
                    text = idea.text.strip().splitlines()[0] if idea.text.strip() else ""
                    rows.append(
                        (
                            SearchKind.IDEA_NOTE,
                            idea.id,
                            text[:80],
                            strings.KIND_LABELS[SearchKind.IDEA_NOTE],
                        )
                    )
        except Exception as exc:
            show_error(self, exc)
            return
        for kind, item_id, title, subtitle in rows[:USES_LIMIT]:
            item = QListWidgetItem(title)
            item.setData(ID_ROLE, item_id)
            item.setData(KIND_ROLE, int(kind))
            item.setData(SUBTITLE_ROLE, subtitle)
            item.setToolTip(title)
            self.uses.addItem(item)
        self.uses_count.setText(local_digits(len(rows)))
        self.uses_count.setVisible(bool(rows))
        self.uses_hint.setText("" if rows else strings.TAG_USES_EMPTY)
        self.uses_hint.setVisible(not rows)

    def _open_use(self, item: QListWidgetItem) -> None:
        kind = SearchKind(int(item.data(KIND_ROLE)))
        item_id = int(item.data(ID_ROLE))
        match kind:
            case SearchKind.EPISODE:
                self.open_episode.emit(item_id)
            case SearchKind.VOICE:
                self.open_voice.emit(item_id)
            case SearchKind.IDEA_NOTE:
                self.open_idea.emit(item_id)

    def _apply_filter(self, text: str) -> None:
        if not text.strip():
            for item in self._items.values():
                item.setHidden(False)
            return
        ranked = [m.tag.id for m in self._ws.tags.suggest(text, limit=200) if m.tag.id]
        visible = set(ranked)
        for tag_id, item in self._items.items():
            item.setHidden(tag_id not in visible)
        current = self.tag_list.currentItem()
        if current is None or current.isHidden():  # keep the selection when it is still shown
            best = next((self._items[i] for i in ranked if i in self._items), None)
            if best is not None:
                self.tag_list.setCurrentItem(best)

    def _changed(self, select_id: int | None = None) -> None:
        self._events.tags_changed.emit()  # triggers refresh() via the connection
        self._events.data_changed.emit()
        if select_id is not None:
            self.refresh(select_id=select_id)

    # actions ---------------------------------------------------------------------------
    def create_tag(self, name: str | None = None) -> int | None:
        """Ask for a new tag's name — by default whatever the filter box is looking for —
        and return the new tag's id, or None when nothing was made."""
        dialog = NewTagDialog(self._ws.tags, self.window())
        dialog.name_edit.setText(self.filter.text().strip() if name is None else name)
        dialog.name_edit.textEdited.emit(dialog.name_edit.text())
        if not dialog.exec():
            return None
        try:
            tag = self._ws.tags.create(dialog.name_edit.text(), allow_similar=True)
        except Exception as exc:
            show_error(self.window(), exc)
            return None
        self.filter.clear()
        self._changed(tag.id)
        return tag.id

    def rename_tag(self) -> None:
        item = self.tag_list.currentItem()
        if item is not None:
            self.tag_list.editItem(item, 0)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        tag_id = int(item.data(0, ID_ROLE))
        tag = self._ws.tags.get(tag_id)
        if tag is None or item.text(0) == tag.name:
            return
        try:
            self._ws.tags.rename(tag_id, item.text(0))
        except Exception as exc:
            show_error(self, exc)
            self._filling = True
            item.setText(0, tag.name)
            self._filling = False
            return
        self._changed(tag_id)

    def recolor_tag(self) -> None:
        tag = self.current_tag()
        if tag is None or tag.id is None:
            return
        color = QColorDialog.getColor(QColor(tag.color), self, strings.TAG_RECOLOR)
        if not color.isValid():
            return
        try:
            self._ws.tags.recolor(tag.id, color.name())
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed(tag.id)

    def merge_tag(self) -> None:
        source = self.current_tag()
        if source is None or source.id is None:
            return
        dialog = TagPickerDialog(
            self._ws.tags, strings.TAG_MERGE_TITLE.format(name=source.name), {source.id}, self
        )
        if not dialog.exec() or dialog.chosen_id is None:
            return
        target = self._ws.tags.get(dialog.chosen_id)
        if target is None or target.id is None:
            return
        text = strings.TAG_MERGE_CONFIRM.format(source=source.name, target=target.name)
        if not confirm(self, text, strings.TAG_MERGE.rstrip("…")):
            return
        try:
            self._ws.tags.merge(source.id, target.id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed(target.id)

    def delete_tag(self) -> None:
        tag = self.current_tag()
        if tag is None or tag.id is None:
            return
        uses = self._ws.tags.usage_counts().get(tag.id, 0)
        if not confirm(
            self, strings.TAG_DELETE_CONFIRM.format(name=tag.name, n=local_digits(uses))
        ):
            return
        try:
            self._ws.tags.delete(tag.id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.filter and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.tag_list.setFocus()
                return True
            if event.key() == Qt.Key.Key_Escape and self.filter.text():
                self.filter.clear()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
