"""Tag manager: create, rename (F2), recolor, nest, unnest, merge, delete."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QColor, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Tag
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import AppEvents, confirm, fa_digits, show_error
from podcast_workspace.ui.widgets.tag_dialogs import NewTagDialog, TagPickerDialog
from podcast_workspace.ui.widgets.tag_widgets import color_dot

ID_ROLE = Qt.ItemDataRole.UserRole


class TagsPage(QWidget):
    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self._items: dict[int, QTreeWidgetItem] = {}
        self._filling = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)
        header = QHBoxLayout()
        header.addWidget(QLabel(strings.TAGS_TITLE, objectName="pageTitle"))
        header.addStretch(1)
        self.primary = QPushButton(strings.TAG_NEW, objectName="primary")
        self.primary.setToolTip("Ctrl+N")
        self.primary.clicked.connect(self.create_tag)
        header.addWidget(self.primary)
        root.addLayout(header)

        self.filter = QLineEdit(placeholderText=strings.TAG_FILTER_PLACEHOLDER)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.filter.installEventFilter(self)
        root.addWidget(self.filter)

        self.tree = QTreeWidget(objectName="tagTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([strings.TAG_NAME_HEADER, strings.TAG_USAGE_HEADER])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)  # F2
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._update_actions())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.tree.installEventFilter(self)
        root.addWidget(self.tree, 1)

        self.empty = QLabel(strings.TAG_EMPTY, objectName="emptyHint")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty)

        buttons = QHBoxLayout()
        self._actions: list[tuple[QAction, QPushButton]] = []
        for label, shortcut, handler in (
            (strings.TAG_RENAME, "F2", self.rename_tag),
            (strings.TAG_RECOLOR, "Ctrl+Shift+C", self.recolor_tag),
            (strings.TAG_NEST, "Ctrl+Shift+N", self.nest_tag),
            (strings.TAG_UNNEST, "Ctrl+Shift+R", self.unnest_tag),
            (strings.TAG_MERGE, "Ctrl+Shift+M", self.merge_tag),
            (strings.TAG_DELETE, "Del", self.delete_tag),
        ):
            action = QAction(label, self.tree)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(handler)
            self.tree.addAction(action)
            button = QPushButton(label, objectName="danger" if handler == self.delete_tag else "")
            button.setToolTip(shortcut)
            button.clicked.connect(handler)
            buttons.addWidget(button)
            self._actions.append((action, button))
        buttons.addStretch(1)
        root.addLayout(buttons)

        new_action = QAction(self, shortcut=QKeySequence.StandardKey.New)
        new_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        new_action.triggered.connect(self.create_tag)
        self.addAction(new_action)
        events.tags_changed.connect(self.refresh)

    # data ------------------------------------------------------------------------------
    def refresh(self, select_id: int | None = None) -> None:
        keep = select_id if select_id is not None else self.current_id()
        tags = self._ws.tags.list_all()
        usage = self._ws.tags.usage_counts()
        self._filling = True
        self.tree.clear()
        self._items = {}
        for tag in tags:
            assert tag.id is not None
            item = QTreeWidgetItem([tag.name, fa_digits(usage.get(tag.id, 0))])
            item.setIcon(0, color_dot(tag.color))
            item.setData(0, ID_ROLE, tag.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
            self._items[tag.id] = item
        for tag in tags:
            assert tag.id is not None
            parent = self._items.get(tag.parent_id) if tag.parent_id is not None else None
            if parent is not None:
                parent.addChild(self._items[tag.id])
            else:
                self.tree.addTopLevelItem(self._items[tag.id])
        self.tree.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.tree.expandAll()
        self._filling = False
        self.tree.setVisible(bool(tags))
        self.empty.setVisible(not tags)
        target = self._items.get(keep) if keep is not None else None
        if target is None and self.tree.topLevelItemCount():
            target = self.tree.topLevelItem(0)
        if target is not None:
            self.tree.setCurrentItem(target)
        self._apply_filter(self.filter.text())
        self._update_actions()

    def current_id(self) -> int | None:
        item = self.tree.currentItem()
        return None if item is None else int(item.data(0, ID_ROLE))

    def current_tag(self) -> Tag | None:
        tag_id = self.current_id()
        return self._ws.tags.get(tag_id) if tag_id is not None else None

    def focus_main(self) -> None:
        self.tree.setFocus()

    def select(self, tag_id: int) -> None:
        self.filter.clear()
        self.refresh(select_id=tag_id)
        self.tree.setFocus()

    def _update_actions(self) -> None:
        tag = self.current_tag()
        for action, button in self._actions:
            enabled = tag is not None
            if action.text() == strings.TAG_UNNEST:
                enabled = tag is not None and tag.parent_id is not None
            action.setEnabled(enabled)
            button.setEnabled(enabled)

    def _apply_filter(self, text: str) -> None:
        if not text.strip():
            for item in self._items.values():
                item.setHidden(False)
            return
        ranked = [m.tag.id for m in self._ws.tags.suggest(text, limit=200) if m.tag.id]
        matched = set(ranked)
        visible: set[int] = set()
        for tag_id in matched:
            item: QTreeWidgetItem | None = self._items.get(tag_id)  # type: ignore[arg-type]
            while item is not None:  # keep ancestors so the hierarchy stays readable
                visible.add(int(item.data(0, ID_ROLE)))
                item = item.parent()
        for tag_id, item in self._items.items():
            item.setHidden(tag_id not in visible)
        current = self.tree.currentItem()
        if current is None or current.isHidden():  # keep the selection when it is still shown
            best = next((self._items[i] for i in ranked if i in self._items), None)
            if best is not None:
                self.tree.setCurrentItem(best)

    def _changed(self, select_id: int | None = None) -> None:
        self._events.tags_changed.emit()  # triggers refresh() via the connection
        self._events.data_changed.emit()
        if select_id is not None:
            self.refresh(select_id=select_id)

    # actions ---------------------------------------------------------------------------
    def create_tag(self) -> None:
        dialog = NewTagDialog(self._ws.tags, self)
        dialog.name_edit.setText(self.filter.text().strip())
        dialog.name_edit.textEdited.emit(dialog.name_edit.text())
        if not dialog.exec():
            return
        try:
            tag = self._ws.tags.create(dialog.name_edit.text(), allow_similar=True)
        except Exception as exc:
            show_error(self, exc)
            return
        self.filter.clear()
        self._changed(tag.id)

    def rename_tag(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.tree.editItem(item, 0)

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

    def _descendants(self, tag_id: int) -> set[int]:
        found: set[int] = set()
        stack = [self._items[tag_id]] if tag_id in self._items else []
        while stack:
            item = stack.pop()
            for i in range(item.childCount()):
                child = item.child(i)
                found.add(int(child.data(0, ID_ROLE)))
                stack.append(child)
        return found

    def nest_tag(self) -> None:
        tag = self.current_tag()
        if tag is None or tag.id is None:
            return
        exclude = {tag.id} | self._descendants(tag.id)
        if tag.parent_id is not None:
            exclude.add(tag.parent_id)
        dialog = TagPickerDialog(
            self._ws.tags, strings.TAG_NEST_TITLE.format(name=tag.name), exclude, self
        )
        if not dialog.exec() or dialog.chosen_id is None:
            return
        try:
            self._ws.tags.set_parent(tag.id, dialog.chosen_id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed(tag.id)

    def unnest_tag(self) -> None:
        tag = self.current_tag()
        if tag is None or tag.id is None or tag.parent_id is None:
            return
        try:
            self._ws.tags.set_parent(tag.id, None)
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
        if not confirm(self, strings.TAG_DELETE_CONFIRM.format(name=tag.name, n=fa_digits(uses))):
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
                self.tree.setFocus()
                return True
            if event.key() == Qt.Key.Key_Escape and self.filter.text():
                self.filter.clear()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
