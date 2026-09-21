"""A short-lived message at the foot of the page, with one optional action.

It exists for changes that are easy to make by accident and easy not to notice — a tag
taken off a voice, a note deleted: the toast says what just happened and puts «undo»
one click away, for the moments the keyboard is not where the user's hands are.

It floats over the page (a child of the content widget, not a window), never takes
focus, and is dismissed by its own × or by time.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

SHOW_MS = 7000
MARGIN = 26
MAX_WIDTH = 620


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
        self._timer = QTimer(self, singleShot=True, interval=SHOW_MS)
        self._timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def show_message(
        self,
        text: str,
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
    ) -> None:
        self.label.setText(text)
        self._on_action = on_action if action_text else None
        self.action.setText(action_text)
        self.action.setVisible(bool(action_text))
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start()

    def dismiss(self) -> None:
        self._timer.stop()
        self._on_action = None
        self.hide()

    def _run(self) -> None:
        action, self._on_action = self._on_action, None
        self.dismiss()
        if action is not None:
            action()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setFixedWidth(min(MAX_WIDTH, max(280, parent.width() - 2 * MARGIN)))
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        self.move(max(MARGIN, x), parent.height() - self.height() - MARGIN)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        resized = watched is self.parentWidget() and event.type() == QEvent.Type.Resize
        if resized and self.isVisible():
            self._place()
        return super().eventFilter(watched, event)
