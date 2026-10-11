"""The app's multi-line text box: plain text, Persian and English side by side.

QPlainTextEdit cannot do this. In a right-to-left window it still puts every line at the
left edge, and Qt gives a line the direction of its first letter, so «Python یک زبان است.»
is laid out left to right with its full stop on the wrong side. Here each paragraph gets
its own direction (`paragraph_direction`): any Persian letter makes it right to left, only
Latin letters make it left to right, and a line without letters (empty, a number, a dash)
follows the line above it — the first one follows the window.

The direction is stored as a block format, and Qt records format changes as undo steps of
their own after the typing that caused them. Undo and redo step over those, so Ctrl+Z
always takes back text, never just a direction.
"""

import unicodedata

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QKeySequence, QTextBlock, QTextCursor
from PySide6.QtWidgets import QMenu, QTextEdit, QWidget

ZWNJ = "‌"  # نیم‌فاصله
_RTL = Qt.LayoutDirection.RightToLeft
_LTR = Qt.LayoutDirection.LeftToRight


def paragraph_direction(text: str) -> Qt.LayoutDirection | None:
    """Right to left if any letter is, left to right if only Latin-like ones; None without
    letters. "Any" rather than Qt's "first": a Persian sentence opening with an English
    word is still a Persian sentence."""
    latin = False
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return _RTL
        latin = latin or kind == "L"
    return _LTR if latin else None


def _is_persian_letter(ch: str) -> bool:
    return unicodedata.bidirectional(ch) == "AL" and unicodedata.category(ch).startswith("L")


class TextEditor(QTextEdit):
    """Plain text in, plain text out; each paragraph laid out in its own direction.
    Shift+Space after a Persian letter types a نیم‌فاصله, as on the standard Persian layout."""

    def __init__(self, parent: QWidget | None = None, **kwargs: object) -> None:
        super().__init__(parent, **kwargs)
        self.setAcceptRichText(False)
        self._replaying = False  # undo/redo running: directions come back with the text
        # Until the first edit, the empty line (and its caret) follows the window.
        option = self.document().defaultTextOption()
        option.setTextDirection(self.layoutDirection())
        self.document().setDefaultTextOption(option)
        self.document().contentsChange.connect(self._on_change)

    # undo / redo that step over direction-only changes ------------------------------------
    def undo(self) -> None:
        self._step(redo=False)

    def redo(self) -> None:
        self._step(redo=True)

    def _step(self, redo: bool) -> None:
        document = self.document()
        available = document.isRedoAvailable if redo else document.isUndoAvailable
        self._replaying = True
        try:
            text = self.toPlainText()
            while available():
                if redo:
                    super().redo()
                else:
                    super().undo()
                # Undo: a step that left the text as it was only set a direction; the
                # typing is under it. Redo: the text is back, its direction is next.
                if redo and self._needs_direction(document.begin(), None):
                    continue
                if not redo and self.toPlainText() == text:
                    continue
                break
        finally:
            self._replaying = False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
        elif event.matches(QKeySequence.StandardKey.Redo) or (
            event.key() == Qt.Key.Key_Z
            and event.modifiers()
            == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        ):
            self.redo()
        elif (
            event.key() == Qt.Key.Key_Space
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
            and not self.isReadOnly()
            and self._after_persian_letter()
        ):
            self.textCursor().insertText(ZWNJ)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = self._menu(event.pos())
        menu.exec(event.globalPos())
        menu.deleteLater()

    def _menu(self, pos: QPoint) -> QMenu:
        menu = self.createStandardContextMenu(pos)
        for action in menu.actions():  # Qt wires these past the overrides above
            if action.objectName() in ("edit-undo", "edit-redo"):
                action.triggered.disconnect()
                action.triggered.connect(
                    self.undo if action.objectName() == "edit-undo" else self.redo
                )
        return menu

    def _after_persian_letter(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection() or cursor.positionInBlock() == 0:
            return False
        return _is_persian_letter(cursor.block().text()[cursor.positionInBlock() - 1])

    # directions ------------------------------------------------------------------------------
    def _on_change(self, position: int, _removed: int, added: int) -> None:
        if self._replaying:
            return
        document = self.document()
        last = document.findBlock(position + added)
        if not last.isValid():
            last = document.lastBlock()
        self._set_directions(document.findBlock(position), last.blockNumber())

    def _wanted(self, block: QTextBlock) -> Qt.LayoutDirection:
        above = block.previous()
        return above.textDirection() if above.isValid() else self.layoutDirection()

    def _needs_direction(self, block: QTextBlock, last: int | None) -> bool:
        """Whether any paragraph from `block` on is not laid out the way it should be."""
        inherited = self._wanted(block)
        while block.isValid():
            direction = paragraph_direction(block.text()) or inherited
            if block.blockFormat().layoutDirection() != direction:
                return True
            if last is not None and block.blockNumber() >= last:
                return False
            inherited = direction
            block = block.next()
        return False

    def _set_directions(self, block: QTextBlock, last: int) -> None:
        """Give the paragraphs up to `last` their direction, and pass it on to the
        letterless lines after them that inherit it."""
        inherited = self._wanted(block)
        cursor: QTextCursor | None = None
        while block.isValid():
            own = paragraph_direction(block.text())
            beyond = block.blockNumber() > last
            if beyond and own is not None:
                break  # it decides for itself, and so for the lines under it
            direction = own or inherited
            form = block.blockFormat()
            if form.layoutDirection() == direction:
                if beyond:
                    break  # already right, so the inheriting lines after it are too
            else:
                if cursor is None:
                    cursor = QTextCursor(self.document())
                    cursor.beginEditBlock()
                cursor.setPosition(block.position())
                form.setLayoutDirection(direction)
                cursor.setBlockFormat(form)
            inherited = direction
            block = block.next()
        if cursor is not None:
            cursor.endEditBlock()
