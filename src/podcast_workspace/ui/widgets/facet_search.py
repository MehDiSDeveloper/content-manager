"""FacetSearchBar — the Ideas page's search: phrases you keep, tags you require, and a
switch that opens the content up to the search.

What is typed filters as you type. Enter keeps it as a chip and empties the box for the
next phrase; every chip and the phrase being typed must all match (AND), so each one
narrows the list and removing one widens it again. Tags have a box of their own, because
"carries this tag" and "mentions this word" are different questions — a word typed in
the search box still finds it in tag names, the way the plain filter boxes do.

Keys in the search box: Enter keeps the phrase (on an empty box it moves to the list),
Down moves to the list, Backspace on an empty box takes back the last chip, Esc empties
the box and then hands the page back.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.list_filter import FacetFilter, parse_list_filter
from podcast_workspace.services.tag_service import TagService
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import AppEvents, direction_mark
from podcast_workspace.ui.widgets.flow_layout import FlowLayout
from podcast_workspace.ui.widgets.tag_input import TagInput


@dataclass(frozen=True)
class FacetState:
    """What the bar held, for Back to put it back."""

    phrases: tuple[str, ...] = ()
    text: str = ""
    tag_ids: tuple[int, ...] = ()
    in_content: bool = False


class PhraseChip(QFrame):
    remove_requested = Signal(str)

    def __init__(self, phrase: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="phraseChip")
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 2, 4, 2)
        row.setSpacing(2)
        row.addWidget(QLabel(f"«{direction_mark(phrase)}{phrase}»"))
        close = QToolButton(text="×", objectName="chipClose")
        close.setToolTip(strings.PHRASE_REMOVE_TOOLTIP)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keyboard: Backspace in the box
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(lambda: self.remove_requested.emit(phrase))
        row.addWidget(close)


class FacetSearchBar(QWidget):
    changed = Signal()
    leave_requested = Signal()  # Down / Enter on an empty box / Esc on an empty box

    def __init__(self, tags: TagService, events: AppEvents, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phrases: list[str] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit = QLineEdit(objectName="listFilter")
        self.edit.setPlaceholderText(strings.IDEA_SEARCH_PLACEHOLDER)
        self.edit.setToolTip(strings.IDEA_SEARCH_TOOLTIP)
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._on_text_changed)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        self.content = QToolButton(objectName="toggleChip", text=strings.CONTENT_SWITCH)
        self.content.setCheckable(True)
        self.content.setCursor(Qt.CursorShape.PointingHandCursor)
        self.content.setToolTip(strings.IDEA_CONTENT_TOOLTIP)
        self.content.toggled.connect(lambda _on: self.changed.emit())
        row.addWidget(self.content)
        col.addLayout(row)

        # Only while something is typed and nothing is kept yet: the one moment the
        # Enter-to-keep gesture is news.
        self.hint = QLabel(strings.IDEA_PIN_HINT, objectName="hint")
        self.hint.hide()
        col.addWidget(self.hint)

        self._chips = QWidget()
        self._flow = FlowLayout(self._chips)
        self._chips.hide()
        col.addWidget(self._chips)

        self.tag_input = TagInput(
            tags, events, allow_create=False, placeholder=strings.IDEA_TAG_FILTER_PLACEHOLDER
        )
        self.tag_input.edit.setObjectName("listFilter")
        self.tag_input.edit.setToolTip(strings.IDEA_TAG_FILTER_TOOLTIP)
        self.tag_input.tags_changed.connect(self._on_tags_changed)
        col.addWidget(self.tag_input)

        self.clear_button = QPushButton(strings.FACETS_CLEAR, objectName="flatButton")
        self.clear_button.setToolTip(strings.FACETS_CLEAR_TOOLTIP)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear)
        self.clear_button.hide()
        # The search's status line; the page puts its match count at the start of it.
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        self.footer.addStretch(1)
        self.footer.addWidget(self.clear_button)
        col.addLayout(self.footer)

    # the filter ------------------------------------------------------------------------
    def facet_filter(self) -> FacetFilter:
        queries = (*self._phrases, self.edit.text())
        return FacetFilter(
            tuple(parse_list_filter(q) for q in queries),
            frozenset(self.tag_input.tag_ids()),
            self.content.isChecked(),
        )

    def in_content(self) -> bool:
        return self.content.isChecked()

    def has_conditions(self) -> bool:
        """Something narrows the list (the content switch alone narrows nothing)."""
        return bool(self._phrases or self.edit.text().strip() or self.tag_input.tag_ids())

    # state -----------------------------------------------------------------------------
    def state(self) -> FacetState:
        return FacetState(
            tuple(self._phrases),
            self.edit.text(),
            tuple(self.tag_input.tag_ids()),
            self.content.isChecked(),
        )

    def restore(self, state: FacetState) -> None:
        """Without a signal: the caller reloads once, afterwards."""
        self.blockSignals(True)
        self._phrases = list(state.phrases)
        self.edit.setText(state.text)
        self.tag_input.set_tag_ids(list(state.tag_ids))
        self.content.setChecked(state.in_content)
        self.blockSignals(False)
        self._render()

    def clear(self) -> None:
        """Every phrase and tag; the content switch is a way of searching, and stays."""
        if not self.has_conditions():
            return
        self.restore(FacetState(in_content=self.content.isChecked()))
        self.changed.emit()

    def focus(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    # behaviour -------------------------------------------------------------------------
    def _pin(self) -> None:
        text = " ".join(self.edit.text().split())
        if parse_list_filter(text).is_empty:
            return
        if text not in self._phrases:
            self._phrases.append(text)
        self.edit.blockSignals(True)
        self.edit.clear()  # same results either way: no reload in between
        self.edit.blockSignals(False)
        self._render()
        self.changed.emit()

    def _unpin(self, phrase: str) -> None:
        if phrase in self._phrases:
            self._phrases.remove(phrase)
            self._render()
            self.changed.emit()
        self.edit.setFocus()

    def _on_text_changed(self, _text: str) -> None:
        self._sync_hint()
        self._sync_clear()
        self.changed.emit()

    def _on_tags_changed(self, _ids: list[int]) -> None:
        self._sync_clear()
        self.changed.emit()

    def _render(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        for phrase in self._phrases:
            chip = PhraseChip(phrase)
            chip.remove_requested.connect(self._unpin)
            self._flow.addWidget(chip)
        self._chips.setVisible(bool(self._phrases))
        self._chips.updateGeometry()
        self._sync_hint()
        self._sync_clear()

    def _sync_hint(self) -> None:
        self.hint.setVisible(bool(self.edit.text().strip()) and not self._phrases)

    def _sync_clear(self) -> None:
        kept = len(self._phrases) + len(self.tag_input.tag_ids())
        self.clear_button.setVisible(kept >= 2 or (kept == 1 and bool(self.edit.text().strip())))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.edit and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.edit.text().strip():
                    self._pin()
                else:
                    self.leave_requested.emit()
                return True
            if key == Qt.Key.Key_Down:
                self.leave_requested.emit()
                return True
            if key == Qt.Key.Key_Escape:
                if self.edit.text():
                    self.edit.clear()
                else:
                    self.leave_requested.emit()
                return True
            if key == Qt.Key.Key_Backspace and not self.edit.text() and self._phrases:
                self._unpin(self._phrases[-1])
                return True
        return super().eventFilter(watched, event)
