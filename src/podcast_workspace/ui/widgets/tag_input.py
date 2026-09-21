"""TagInput — the single place where tags get attached to anything.

Typing shows forgiving live suggestions of existing tags. Enter picks the highlighted
row, and the highlighted row is always an existing tag when one matches, so a
near-duplicate can only be created by deliberately choosing the "create" row.

With `allow_create=False` it picks among existing tags only: a search filter, not an
editor, where a tag that does not exist yet has nothing to find.
"""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from podcast_workspace.domain.entities import Tag
from podcast_workspace.domain.tag_matching import NEAR_DUPLICATE_THRESHOLD
from podcast_workspace.services.tag_service import TagService
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import AppEvents, local_digits, show_error
from podcast_workspace.ui.widgets.flow_layout import FlowLayout
from podcast_workspace.ui.widgets.tag_widgets import KIND_CREATE, SuggestionList, TagChip


class TagInput(QWidget):
    tags_changed = Signal(list)  # list[int]

    def __init__(
        self,
        tags: TagService,
        events: AppEvents,
        limit: int | None = None,
        parent: QWidget | None = None,
        allow_create: bool = True,
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self._tags = tags
        self._events = events
        self._limit = limit
        self._allow_create = allow_create
        self._placeholder = placeholder or strings.TAG_INPUT_PLACEHOLDER
        self._ids: list[int] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        self._chips = QWidget()
        self._flow = FlowLayout(self._chips)
        col.addWidget(self._chips)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit(placeholderText=self._placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.textEdited.connect(self._update_suggestions)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        self._counter = QLabel(objectName="muted")
        self._counter.setVisible(limit is not None)
        row.addWidget(self._counter)
        col.addLayout(row)

        self._list = SuggestionList()
        self._list.setVisible(False)
        self._list.activated_value.connect(self._on_activated)
        col.addWidget(self._list)

        events.tags_changed.connect(self._render)
        self._render()

    # public API -----------------------------------------------------------------------
    def tag_ids(self) -> list[int]:
        return list(self._ids)

    def set_tag_ids(self, tag_ids: set[int] | list[int]) -> None:
        """Replace the shown tags without emitting tags_changed."""
        known = {t.id: t for t in self._tags.list_all()}
        self._ids = sorted((i for i in tag_ids if i in known), key=lambda i: known[i].name)
        self.edit.clear()
        self._list.setVisible(False)
        self._render()

    # behaviour ------------------------------------------------------------------------
    def _full(self) -> bool:
        return self._limit is not None and len(self._ids) >= self._limit

    def _render(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        by_id = {t.id: t for t in self._tags.by_ids(self._ids)}
        self._ids = [i for i in self._ids if i in by_id]  # a tag may have been deleted/merged
        for tag_id in self._ids:
            chip = TagChip(by_id[tag_id])
            chip.remove_requested.connect(self._remove)
            self._flow.addWidget(chip)
        self._chips.setVisible(bool(self._ids))
        self._chips.updateGeometry()
        if self._limit is not None:
            self._counter.setText(
                strings.TAG_INPUT_COUNT.format(
                    n=local_digits(len(self._ids)), limit=local_digits(self._limit)
                )
            )
        full = self._full()
        self.edit.setReadOnly(full)
        self.edit.setPlaceholderText(
            strings.TAG_INPUT_FULL.format(limit=local_digits(self._limit))
            if full
            else self._placeholder
        )

    def _parent_name(self, tag: Tag) -> str | None:
        if tag.parent_id is None:
            return None
        parent = self._tags.get(tag.parent_id)
        return parent.name if parent else None

    def _update_suggestions(self, text: str) -> None:
        if not text.strip() or self._full():
            self._list.setVisible(False)
            return
        attached = set(self._ids)
        matches = self._tags.suggest(text, exclude_ids=attached)
        create: tuple[str, str] | None = None
        exact = self._tags.find_exact(text)
        if exact is None and self._allow_create:
            name = " ".join(text.split())
            similar = [m.tag.name for m in matches if m.score >= NEAR_DUPLICATE_THRESHOLD] or [
                t.name for t in self._tags.similar_to(name)
            ]
            label = (
                strings.TAG_INPUT_CREATE_SIMILAR.format(name=name, similar=similar[0])
                if similar
                else strings.TAG_INPUT_CREATE.format(name=name)
            )
            create = (label, name)
        elif exact is not None and exact.id in attached:
            matches = [m for m in matches if m.tag.id != exact.id]
        self._list.fill([m.tag for m in matches], self._parent_name, create)

    def _on_activated(self, kind: str, value: object) -> None:
        if kind == KIND_CREATE:
            try:
                tag = self._tags.create(str(value), allow_similar=True)
            except Exception as exc:
                show_error(self, exc)
                return
            self._events.tags_changed.emit()
            assert tag.id is not None
            self._add(tag.id)
        else:
            self._add(int(str(value)))

    def _add(self, tag_id: int) -> None:
        if tag_id in self._ids or self._full():
            return
        self._ids.append(tag_id)
        self.edit.clear()
        self._list.setVisible(False)
        self._render()
        self.tags_changed.emit(self.tag_ids())

    def _remove(self, tag_id: int) -> None:
        if tag_id in self._ids:
            self._ids.remove(tag_id)
            self._render()
            self.tags_changed.emit(self.tag_ids())
            self.edit.setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.edit and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            suggestions_open = self._list.isVisible()
            if key == Qt.Key.Key_Down and suggestions_open:
                self._list.move(1)
                return True
            if key == Qt.Key.Key_Up and suggestions_open:
                self._list.move(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and suggestions_open:
                self._list.activate_current()
                return True
            if key == Qt.Key.Key_Escape and (suggestions_open or self.edit.text()):
                self.edit.clear()
                self._list.setVisible(False)
                return True
            if key == Qt.Key.Key_Backspace and not self.edit.text() and self._ids:
                self._remove(self._ids[-1])
                return True
        if watched is self.edit and event.type() == QEvent.Type.FocusOut:
            self._list.setVisible(False)
        return super().eventFilter(watched, event)
