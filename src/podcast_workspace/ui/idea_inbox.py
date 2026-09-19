"""Idea Inbox: a tiny always-on-top window opened by the global hotkey.

Type, Enter saves an IdeaNote and closes; Esc (or clicking away with nothing typed) closes.
"""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.hotkey import force_foreground
from podcast_workspace.ui.support import show_error

WIDTH, HEIGHT = 480, 190


class IdeaInbox(QWidget):
    saved = Signal(int)  # idea id

    def __init__(self, workspace: Workspace) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._ws = workspace
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setWindowTitle(strings.INBOX_TITLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame(objectName="inboxFrame")
        outer.addWidget(frame)
        col = QVBoxLayout(frame)
        col.setContentsMargins(18, 14, 18, 12)
        col.setSpacing(8)
        col.addWidget(QLabel(strings.INBOX_TITLE, objectName="sectionTitle"))
        self.text = QPlainTextEdit(objectName="inboxText")
        self.text.setPlaceholderText(strings.INBOX_PLACEHOLDER)
        self.text.setTabChangesFocus(True)
        self.text.installEventFilter(self)
        col.addWidget(self.text, 1)
        col.addWidget(QLabel(strings.INBOX_HINT, objectName="muted"))

    def summon(self) -> None:
        """Show centred in the upper third of the screen under the mouse, focused."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(QPoint(area.center().x() - WIDTH // 2, area.top() + area.height() // 4))
        self.show()
        self.raise_()
        self.activateWindow()
        force_foreground(int(self.winId()))
        self.text.setFocus()

    def _save(self) -> None:
        text = self.text.toPlainText()
        if not text.strip():
            self.close()
            return
        try:
            idea = self._ws.ideas.create(text)
        except Exception as exc:
            show_error(self, exc)
            return
        self.text.clear()
        self.close()
        if idea.id is not None:
            self.saved.emit(idea.id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.text and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._save()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        # Clicking elsewhere closes an empty inbox; typed text is kept until Esc or Enter.
        if (
            event.type() == QEvent.Type.ActivationChange
            and not self.isActiveWindow()
            and not self.text.toPlainText().strip()
        ):
            self.close()
        super().changeEvent(event)
