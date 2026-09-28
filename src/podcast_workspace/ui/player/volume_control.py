"""Playback volume beside the clock: a speaker button that drops a level slider, with the
mouse wheel over it changing the level directly and M muting from anywhere on the page.

The level lives on the shared `Player` (remembered between runs; muting is for the session),
so the players on different pages show the same one. It changes what is heard, never the file.
"""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPalette, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QToolTip, QWidget

from podcast_workspace.audio.engine import MAX_VOLUME, Player
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.icons import ICON_SIZE, volume_icon
from podcast_workspace.ui.player.popup import PlayerPopup
from podcast_workspace.ui.support import local_digits

STEP = 5  # a wheel notch or an arrow key
WHEEL_NOTCH = 120  # angleDelta units
SLIDER_WIDTH = 160
LOUD_FROM = 50  # the speaker draws its second wave from this level on


def _speaker(button: QToolButton, player: Player) -> None:
    """Paint `button`'s icon for the player's level, in its own text colour."""
    waves = -1 if player.muted else 2 if player.volume >= LOUD_FROM else 1
    color = button.palette().color(QPalette.ColorRole.ButtonText)
    button.setIcon(volume_icon(color, waves))


def _percent(player: Player) -> str:
    return strings.PLAYER_VOLUME_PERCENT.format(percent=local_digits(player.volume))


class VolumePopup(PlayerPopup):
    def __init__(self, player: Player, parent: QWidget) -> None:
        super().__init__(parent, "volumePopup")
        self.player = player
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 14, 8)
        row.setSpacing(8)
        self.mute = QToolButton(objectName="volumeButton")
        self.mute.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.mute.clicked.connect(player.toggle_mute)
        row.addWidget(self.mute)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, MAX_VOLUME)
        self.slider.setSingleStep(STEP)
        self.slider.setPageStep(2 * STEP)
        self.slider.setFixedWidth(SLIDER_WIDTH)
        self.slider.valueChanged.connect(player.set_volume)
        self.keep_slider_keys(self.slider)
        row.addWidget(self.slider)
        self.value = QLabel(objectName="volumeValue")
        self.value.setMinimumWidth(self.value.fontMetrics().horizontalAdvance("۱۰۰٪ "))
        row.addWidget(self.value)
        player.volume_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.player.volume)
        self.slider.blockSignals(False)
        self.value.setText(_percent(self.player))
        self.mute.setToolTip(
            strings.PLAYER_UNMUTE_TOOLTIP if self.player.muted else strings.PLAYER_MUTE_TOOLTIP
        )
        _speaker(self.mute, self.player)


class VolumeButton(QToolButton):
    def __init__(self, player: Player) -> None:
        super().__init__(objectName="volumeButton")
        self.player = player
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._wheel = 0
        self.popup = VolumePopup(player, self)
        self.clicked.connect(lambda: self.popup.show_under(self))
        player.volume_changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.setToolTip(strings.PLAYER_VOLUME_TOOLTIP.format(level=_percent(self.player)))
        _speaker(self, self.player)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # A touchpad sends fractions of a notch: count them up.
        self._wheel += event.angleDelta().y()
        notches = int(self._wheel / WHEEL_NOTCH)
        if notches:
            self._wheel -= notches * WHEEL_NOTCH
            self.player.step_volume(notches * STEP)
            QToolTip.showText(event.globalPosition().toPoint(), _percent(self.player), self)
        event.accept()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            _speaker(self, self.player)
        super().changeEvent(event)
