"""«حذف سکوت» beside the speed button: a one-click switch, and a ▾ beside it opening a popup
with the 0–2 s «pause to keep» slider.

Everything is held by the shared `Player`, so the players on different pages show the same
setting; this widget only reflects it and forwards changes.
"""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.audio.silence import KEEP_STEP_MS, MAX_KEEP_MS, total_ms
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.icons import ICON_SIZE, chevron_icon, silence_icon
from podcast_workspace.ui.player.popup import PlayerPopup
from podcast_workspace.ui.support import format_clock, local_digits

POPUP_WIDTH = 320


def seconds_label(ms: int) -> str:
    if ms <= 0:
        return strings.SILENCE_KEEP_NONE
    value = local_digits(f"{ms / 1000:g}").replace(".", strings.DECIMAL_SEPARATOR)
    return strings.SILENCE_SECONDS.format(value=value)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class SilencePopup(PlayerPopup):
    def __init__(self, player: Player, parent: QWidget) -> None:
        super().__init__(parent, "silencePopup")
        self.player = player
        self.setFixedWidth(POPUP_WIDTH)

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)
        self.enable = QCheckBox(strings.SILENCE_ENABLE)
        self.enable.toggled.connect(player.set_skip_silence)
        col.addWidget(self.enable)
        hint = QLabel(strings.SILENCE_HINT, objectName="muted")
        hint.setWordWrap(True)
        col.addWidget(hint)
        col.addSpacing(4)

        head = QHBoxLayout()
        head.addWidget(QLabel(strings.SILENCE_KEEP_LABEL, objectName="fieldLabel"))
        head.addStretch(1)
        self.value = QLabel(objectName="silenceValue")
        head.addWidget(self.value)
        col.addLayout(head)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, MAX_KEEP_MS // KEEP_STEP_MS)
        self.slider.setSingleStep(1)  # 0.05 s with the arrows
        self.slider.setPageStep(500 // KEEP_STEP_MS)  # 0.5 s with PgUp/PgDn
        self.slider.valueChanged.connect(self._on_slider)
        self.keep_slider_keys(self.slider)
        # A time scale, like the waveform and the transport: left to right in every language.
        track = QWidget()
        track.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        track_col = QVBoxLayout(track)
        track_col.setContentsMargins(0, 0, 0, 0)
        track_col.setSpacing(2)
        track_col.addWidget(self.slider)
        scale = QHBoxLayout()
        scale.addWidget(QLabel(local_digits(0), objectName="muted"))
        scale.addStretch(1)
        scale.addWidget(QLabel(seconds_label(MAX_KEEP_MS), objectName="muted"))
        track_col.addLayout(scale)
        col.addWidget(track)
        col.addSpacing(2)
        self.summary = QLabel(objectName="muted")
        self.summary.setWordWrap(True)
        col.addWidget(self.summary)

        player.silence_changed.connect(self.refresh)
        player.duration_changed.connect(lambda _ms: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        player = self.player
        for widget in (self.enable, self.slider):
            widget.blockSignals(True)
        self.enable.setChecked(player.skip_silence)
        self.slider.setValue(player.keep_pause_ms // KEEP_STEP_MS)
        for widget in (self.enable, self.slider):
            widget.blockSignals(False)
        self.value.setText(seconds_label(player.keep_pause_ms))
        self.summary.setText(self._summary())

    def _summary(self) -> str:
        player = self.player
        if not player.source:
            return ""
        if not player.pauses_known:
            return strings.SILENCE_READING
        saved = total_ms(player.silence_cuts())
        if saved <= 0 or player.duration <= 0:
            return strings.SILENCE_NOTHING
        percent = local_digits(round(100 * saved / player.duration))
        if not player.skip_silence:
            return strings.SILENCE_SAVING_OFF.format(saved=format_clock(saved), percent=percent)
        return strings.SILENCE_SAVING.format(
            saved=format_clock(saved), percent=percent, total=format_clock(player.duration)
        )

    def _on_slider(self, steps: int) -> None:
        # Choosing how much pause to keep means wanting the pauses trimmed.
        self.player.set_keep_pause(steps * KEEP_STEP_MS)
        self.player.set_skip_silence(True)


class SilenceControl(QFrame):
    """A split button: the wide part switches trimming on and off in one click (or S), the
    narrow ▾ beside it opens the pause-length popup."""

    def __init__(self, player: Player) -> None:
        super().__init__(objectName="silenceGroup")
        self.player = player
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.toggle = QToolButton(objectName="silenceButton")
        self.toggle.setText(strings.PLAYER_SILENCE)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setIconSize(QSize(ICON_SIZE - 2, ICON_SIZE - 2))
        self.toggle.toggled.connect(player.set_skip_silence)
        row.addWidget(self.toggle)
        self.more = QToolButton(objectName="silenceMore")
        self.more.setToolTip(strings.PLAYER_SILENCE_MORE_TOOLTIP)
        self.more.setIconSize(QSize(ICON_SIZE - 4, ICON_SIZE - 4))
        row.addWidget(self.more)
        self.popup = SilencePopup(player, self.more)
        self.more.clicked.connect(lambda: self.popup.show_under(self))
        player.silence_changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        on = self.player.skip_silence
        self.toggle.blockSignals(True)
        self.toggle.setChecked(on)
        self.toggle.blockSignals(False)
        for button in (self.toggle, self.more):
            if button.property("active") != on:
                button.setProperty("active", on)
                _repolish(button)
        self.toggle.setToolTip(
            strings.PLAYER_SILENCE_TOOLTIP_ON.format(keep=seconds_label(self.player.keep_pause_ms))
            if on
            else strings.PLAYER_SILENCE_TOOLTIP_OFF
        )
        self._paint_icons()

    def _paint_icons(self) -> None:
        role = (
            QPalette.ColorRole.HighlightedText  # ink on the accent fill
            if self.player.skip_silence
            else QPalette.ColorRole.ButtonText
        )
        color = self.palette().color(role)
        self.toggle.setIcon(silence_icon(color))
        self.more.setIcon(chevron_icon(color))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icons()
        super().changeEvent(event)
