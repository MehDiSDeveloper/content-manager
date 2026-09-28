"""The small settings panels the transport row's buttons drop down (volume, pause trimming)."""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QFrame, QSlider, QWidget

# Keys a popup's slider keeps for itself: the page binds the arrows to seeking.
SLIDER_KEYS = frozenset(
    {
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_PageDown,
    }
)


class PlayerPopup(QFrame):
    """A Qt popup: a click elsewhere or Esc closes it. It opens with its slider focused."""

    def __init__(self, parent: QWidget, object_name: str) -> None:
        super().__init__(parent, Qt.WindowType.Popup, objectName=object_name)
        # The transport row is always left-to-right; the popup reads like the rest of the UI.
        self.setLayoutDirection(QGuiApplication.layoutDirection())
        # A click on the button while open only closes the popup, it does not reopen it.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._slider: QSlider | None = None

    def keep_slider_keys(self, slider: QSlider) -> None:
        self._slider = slider
        slider.installEventFilter(self)

    def refresh(self) -> None:
        """Show the player's current state; called before every opening."""

    def show_under(self, anchor: QWidget) -> None:
        self.refresh()
        self.adjustSize()
        screen = (anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        below = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        # Line the popup's far edge up with the button's, on the side the UI reads from.
        x = below.x() + anchor.width() - self.width() if self.isRightToLeft() else below.x()
        y = below.y()
        if y + self.height() > screen.bottom():
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
        x = max(screen.left(), min(x, screen.right() - self.width()))
        self.move(x, y)
        self.show()
        if self._slider is not None:
            self._slider.setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._slider
            and event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and event.key() in SLIDER_KEYS
        ):
            event.accept()  # the key reaches the slider instead of the page's shortcut
            return True
        return super().eventFilter(watched, event)
