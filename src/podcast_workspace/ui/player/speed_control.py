"""Playback speed on the transport row: a button showing the speed that drops a 0.5–2×
slider in 5% steps, with − / + for one step and the usual presets one click away. The mouse
wheel over the button moves one step per notch; - and = step through the presets from
anywhere on the page.

The speed lives on the shared `Player`, so the players on different pages show the same one.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import MAX_SPEED, MIN_SPEED, SPEED_STEP, SPEEDS, Player
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.popup import PlayerPopup
from podcast_workspace.ui.support import local_digits

POPUP_WIDTH = 340
WHEEL_NOTCH = 120  # angleDelta units


def speed_label(speed: float) -> str:
    return local_digits(f"{speed:g}").replace(".", strings.DECIMAL_SEPARATOR) + "×"


def _steps(speed: float) -> int:
    """The slider's position for `speed`: whole 5% steps."""
    return round(speed / SPEED_STEP)


class SpeedPopup(PlayerPopup):
    def __init__(self, player: Player, parent: QWidget) -> None:
        super().__init__(parent, "speedPopup")
        self.player = player
        self.setMinimumWidth(POPUP_WIDTH)  # wider if the presets need it

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel(strings.SPEED_LABEL, objectName="fieldLabel"))
        head.addStretch(1)
        self.value = QLabel(objectName="speedValue")
        head.addWidget(self.value)
        col.addLayout(head)

        # A scale like the volume's: faster to the right in every language.
        track = QWidget()
        track.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row = QHBoxLayout(track)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.slower = self._step_button("−", strings.SPEED_SLOWER_TOOLTIP, -1)
        row.addWidget(self.slower)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(_steps(MIN_SPEED), _steps(MAX_SPEED))
        self.slider.setSingleStep(1)  # 5% with the arrows
        self.slider.setPageStep(_steps(0.25))  # a preset's distance with PgUp/PgDn
        self.slider.valueChanged.connect(
            lambda steps: player.set_speed(steps * SPEED_STEP, settle=True)
        )
        self.keep_slider_keys(self.slider)
        row.addWidget(self.slider, 1)
        self.faster = self._step_button("+", strings.SPEED_FASTER_TOOLTIP, 1)
        row.addWidget(self.faster)
        col.addWidget(track)

        presets = QWidget()
        presets.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        chips = QHBoxLayout(presets)
        chips.setContentsMargins(0, 2, 0, 0)
        chips.setSpacing(4)
        self._presets = QButtonGroup(self)
        self._presets.setExclusive(False)  # an in-between speed leaves none of them checked
        for value in SPEEDS:
            chip = QToolButton(objectName="speedPreset", text=speed_label(value))
            chip.setCheckable(True)
            chip.clicked.connect(lambda _c=False, v=value: player.set_speed(v))
            self._presets.addButton(chip, _steps(value))
            chips.addWidget(chip, 1)
        col.addWidget(presets)

        player.speed_changed.connect(lambda _s: self.refresh())
        self.refresh()

    def _step_button(self, text: str, tooltip: str, direction: int) -> QToolButton:
        button = QToolButton(objectName="speedStep", text=text)
        button.setToolTip(tooltip)
        button.setAutoRepeat(True)
        button.clicked.connect(
            lambda: self.player.set_speed(self.player.speed + direction * SPEED_STEP, settle=True)
        )
        return button

    def refresh(self) -> None:
        speed = self.player.speed
        self.slider.blockSignals(True)
        self.slider.setValue(_steps(speed))
        self.slider.blockSignals(False)
        self.value.setText(speed_label(speed))
        for chip in self._presets.buttons():
            chip.setChecked(self._presets.id(chip) == _steps(speed))
        self.slower.setEnabled(speed > MIN_SPEED)
        self.faster.setEnabled(speed < MAX_SPEED)


class SpeedButton(QToolButton):
    def __init__(self, player: Player) -> None:
        super().__init__(objectName="speedButton")
        self.player = player
        self.setToolTip(strings.PLAYER_SPEED_TOOLTIP)
        self._wheel = 0
        self.popup = SpeedPopup(player, self)
        self.clicked.connect(lambda: self.popup.show_under(self))
        player.speed_changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.setText(speed_label(self.player.speed))

    def wheelEvent(self, event: QWheelEvent) -> None:
        # A touchpad sends fractions of a notch: count them up.
        self._wheel += event.angleDelta().y()
        notches = int(self._wheel / WHEEL_NOTCH)
        if notches:
            self._wheel -= notches * WHEEL_NOTCH
            self.player.set_speed(self.player.speed + notches * SPEED_STEP, settle=True)
            QToolTip.showText(
                event.globalPosition().toPoint(), speed_label(self.player.speed), self
            )
        event.accept()

    def sizeHint(self) -> QSize:
        # Wide enough for "۱٫۷۵×" so the row does not shift as the speed changes.
        hint = super().sizeHint()
        widest = self.fontMetrics().horizontalAdvance(speed_label(1.75))
        return QSize(max(hint.width(), widest + 24), hint.height())
