"""Paragraph direction in the text editor: Persian with English words, undo that never
stops on a direction-only step, and the نیم‌فاصله on Shift+Space."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from podcast_workspace.ui.widgets.text_editor import ZWNJ, TextEditor, paragraph_direction

RTL = Qt.LayoutDirection.RightToLeft
LTR = Qt.LayoutDirection.LeftToRight


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("سلام دنیا", RTL),
        ("Python یک زبان است.", RTL),  # Qt's first-letter rule would say LTR
        ("Docker Compose رو نصب کن", RTL),
        ("Hello world.", LTR),
        ("https://example.com/a", LTR),
        ("", None),
        ("۱۲۳ - 45", None),
    ],
)
def test_paragraph_direction(text: str, expected: Qt.LayoutDirection | None) -> None:
    assert paragraph_direction(text) == expected


@pytest.fixture
def editor() -> TextEditor:
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(RTL)
    return TextEditor()


def _type(editor: TextEditor, text: str) -> None:
    for ch in text:  # QTest.keyClicks crashes on Persian text
        if ch == "\n":
            key, ch = Qt.Key.Key_Return, "\r"
        else:
            key = 0
        QApplication.sendEvent(
            editor, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, ch)
        )


def _key(editor: TextEditor, key: Qt.Key, modifiers: Qt.KeyboardModifier, text: str) -> None:
    QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text))


def _directions(editor: TextEditor) -> list[Qt.LayoutDirection]:
    out, block = [], editor.document().begin()
    while block.isValid():
        out.append(block.textDirection())
        block = block.next()
    return out


def test_letterless_lines_follow_the_line_above(editor: TextEditor) -> None:
    editor.setPlainText("سلام\n\n۱۲۳\nHello\n\n- 1\nPython یک")
    assert _directions(editor) == [RTL, RTL, RTL, LTR, LTR, LTR, RTL]
    assert not editor.document().isUndoAvailable()  # loading is not an edit


def test_direction_follows_typing_and_undo_takes_back_text(editor: TextEditor) -> None:
    assert _directions(editor) == [RTL]  # empty: the window's direction
    _type(editor, "Python")
    assert _directions(editor) == [LTR]
    _type(editor, " یک\n")
    assert _directions(editor) == [RTL, RTL]
    _type(editor, "Hi")
    assert _directions(editor) == [RTL, LTR]

    seen = []
    while editor.document().isUndoAvailable():
        before = editor.toPlainText()
        _key(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "z")
        assert editor.toPlainText() != before  # every Ctrl+Z changes the text
        seen.append((editor.toPlainText(), _directions(editor)))
    assert seen[-1] == ("", [RTL])
    for text, directions in seen:
        lines = text.split("\n")
        expected = [paragraph_direction(line) for line in lines]
        filled = []
        for direction in expected:
            filled.append(direction or (filled[-1] if filled else RTL))
        assert directions == filled, text

    while editor.document().isRedoAvailable():
        editor.redo()
    assert editor.toPlainText() == "Python یک\nHi"
    assert _directions(editor) == [RTL, LTR]


def test_shift_space_after_persian_is_a_zwnj(editor: TextEditor) -> None:
    _type(editor, "می")
    _key(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier, " ")
    _type(editor, "خواهم I")
    _key(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier, " ")
    _type(editor, "Am")
    assert editor.toPlainText() == f"می{ZWNJ}خواهم I Am"
