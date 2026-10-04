"""A short-lived message at the foot of the page, with one optional action.

It exists for changes that are easy to make by accident and easy not to notice — a tag
taken off a voice, a note deleted: the toast says what just happened and puts «undo»
one click away, for the moments the keyboard is not where the user's hands are.

It floats over the page (a child of the content widget, not a window), never takes
focus, and is dismissed by its own × or by time. It is only as wide as its message, so a
short one covers as little of the page's own buttons as it can.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

SHOW_MS = 7000
MARGIN = 26
MAX_WIDTH = 620
MIN_WIDTH = 280


class Toast(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, objectName="toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMaximumWidth(MAX_WIDTH)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(10)
        self.label = QLabel(objectName="toastText")
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        self.action = QPushButton(objectName="toastAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action.clicked.connect(self._run)
        row.addWidget(self.action)
        self.close_button = QToolButton(objectName="toastClose")
        self.close_button.setText("×")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.dismiss)
        row.addWidget(self.close_button)

        self._on_action: Callable[[], None] | None = None
        self._key = ""
        self._timer = QTimer(self, singleShot=True, interval=SHOW_MS)
        self._timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def show_message(
        self,
        text: str,
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
        show_ms: int = SHOW_MS,
        key: str = "",
    ) -> None:
        """`key` names a message that may be withdrawn later with `dismiss_if`."""
        self._key = key
        self.label.setText(text)
        self._on_action = on_action if action_text else None
        self.action.setText(action_text)
        self.action.setVisible(bool(action_text))
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(show_ms)

    def dismiss(self) -> None:
        self._timer.stop()
        self._on_action = None
        self._key = ""
        self.hide()

    def dismiss_if(self, key: str) -> None:
        """Withdraw the message shown under `key`, and only that one."""
        if self.isVisible() and self._key == key:
            self.dismiss()

    def _run(self) -> None:
        action, self._on_action = self._on_action, None
        self.dismiss()
        if action is not None:
            action()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        room = max(MIN_WIDTH, min(MAX_WIDTH, parent.width() - 2 * MARGIN))
        self.setFixedWidth(max(MIN_WIDTH, min(room, self._content_width())))
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        self.move(max(MARGIN, x), parent.height() - self.height() - MARGIN)

    def _content_width(self) -> int:
        """The width that fits the message on one line, with the buttons beside it."""
        row = self.layout()
        margins = row.contentsMargins()
        width = margins.left() + margins.right()
        width += self.label.fontMetrics().horizontalAdvance(self.label.text()) + 4
        for button in (self.action, self.close_button):
            if not button.isHidden():
                width += row.spacing() + button.sizeHint().width()
        return width

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        resized = watched is self.parentWidget() and event.type() == QEvent.Type.Resize
        if resized and self.isVisible():
            self._place()
        return super().eventFilter(watched, event)
