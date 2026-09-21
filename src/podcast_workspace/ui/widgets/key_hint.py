"""Keycaps beside the controls they trigger: a shortcut seen every time is one that gets
learnt, where one kept in a tooltip never is.

`KeyHint` is the keycap itself, for a layout next to a button. `attach_key_hint` puts one
inside a line edit, against its trailing edge, for as long as the box is empty — once
something is typed that corner belongs to the clear button.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget

INSET = 7  # from the box's edge to the keycap
GAP = 6  # between the keycap and the text


class KeyHint(QLabel):
    def __init__(self, keys: str, parent: QWidget | None = None) -> None:
        super().__init__(keys, parent, objectName="keyHint")
        # "Ctrl+K" is Latin and reads left to right in the Persian UI too.
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Its own size, never the row's: a keycap stretched to a button's height reads
        # as another button.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class _InEdit(QObject):
    def __init__(self, edit: QLineEdit, hint: KeyHint) -> None:
        super().__init__(edit)
        self._edit = edit
        self._hint = hint
        edit.installEventFilter(self)
        edit.textChanged.connect(lambda _t: self.sync())
        self.sync()

    def sync(self) -> None:
        edit, hint = self._edit, self._hint
        shown = not edit.text() and edit.isEnabled()
        hint.setVisible(shown)
        hint.adjustSize()
        room = hint.width() + INSET + GAP if shown else 0
        # Text margins are physical: the trailing edge is the left one in RTL.
        rtl = edit.isRightToLeft()
        edit.setTextMargins(room if rtl else 0, 0, 0 if rtl else room, 0)
        x = INSET if rtl else edit.width() - hint.width() - INSET
        hint.move(x, (edit.height() - hint.height()) // 2)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.LayoutDirectionChange,
            QEvent.Type.EnabledChange,
            QEvent.Type.StyleChange,
        ):
            self.sync()
        return False


def attach_key_hint(edit: QLineEdit, keys: str) -> KeyHint:
    hint = KeyHint(keys, edit)
    _InEdit(edit, hint)
    return hint


def add_key_hint(layout: QBoxLayout, widget: QWidget, keys: str) -> KeyHint:
    """Put a keycap right after `widget` in its layout (reading order: after the label)."""
    hint = KeyHint(keys)
    layout.insertWidget(layout.indexOf(widget) + 1, hint)
    return hint
