"""The number before a season's or an episode's title: its place in the order."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractSpinBox, QSpinBox

from podcast_workspace.ui import strings

MAX_NUMBER = 999


class NumberBox(QSpinBox):
    """0 shows as «#»: not numbered yet. Saves on Enter, leaving, or an arrow step."""

    number_changed = Signal(object)  # int | None

    def __init__(self, tooltip: str) -> None:
        super().__init__(objectName="numberBox")
        self.setRange(0, MAX_NUMBER)
        self.setSpecialValueText(strings.NUMBER_NONE)
        self.setToolTip(tooltip)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance("0000") * 2)
        self.setKeyboardTracking(False)  # one save per number, not per digit typed
        self.valueChanged.connect(lambda n: self.number_changed.emit(n or None))

    def set_number(self, number: int | None) -> None:
        self.blockSignals(True)
        self.setValue(number or 0)
        self.blockSignals(False)
