"""A one-line label that gives up width gracefully: in a narrow pane it shortens its text
with «…» (the whole of it in the tooltip) instead of pushing the buttons beside it out of
the window, or wrapping into a row that does not grow to show the second line."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

MIN_WIDTH = 40


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        objectName: str = "",  # noqa: N803 — Qt's own spelling, as on every widget
    ) -> None:
        super().__init__(parent, objectName=objectName)
        self._mode = mode
        self._full = ""
        self._own_tooltip = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full = text
        self.updateGeometry()
        self._elide()

    def text(self) -> str:  # type: ignore[override]
        return self._full

    def setToolTip(self, tip: str) -> None:  # type: ignore[override]
        self._own_tooltip = tip
        super().setToolTip(tip)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 4, hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(min(MIN_WIDTH, self.sizeHint().width()), super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, self._mode, self.width())
        super().setText(shown)
        # A caller's own tooltip wins; otherwise a shortened text carries the whole one.
        if not self._own_tooltip:
            super().setToolTip(self._full if shown != self._full else "")
