"""«حذف سکوت» beside the speed button: a switch and a 0–2 s «pause to keep» slider in a popup.

Everything is held by the shared `Player`, so the players on different pages show the same
setting; this widget only reflects it and forwards changes.
"""

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QPalette
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
from podcast_workspace.ui.player.icons import ICON_SIZE, silence_icon
from podcast_workspace.ui.support import format_clock, local_digits

POPUP_WIDTH = 320
# Keys the slider keeps for itself: the page binds the arrows to seeking.
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


def seconds_label(ms: int) -> str:
    if ms <= 0:
        return strings.SILENCE_KEEP_NONE
    value = local_digits(f"{ms / 1000:g}").replace(".", strings.DECIMAL_SEPARATOR)
    return strings.SILENCE_SECONDS.format(value=value)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class SilencePopup(QFrame):
    def __init__(self, player: Player, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup, objectName="silencePopup")
        self.player = player
        # The transport row is always left-to-right; the popup reads like the rest of the UI.
        self.setLayoutDirection(QGuiApplication.layoutDirection())
        # A click on the button while open only closes the popup, it does not reopen it.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
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
        self.slider.installEventFilter(self)
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
        self.slider.setFocus()

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.slider
            and event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and event.key() in SLIDER_KEYS
        ):
            event.accept()  # the key reaches the slider instead of the page's shortcut
            return True
        return super().eventFilter(watched, event)

    def _on_slider(self, steps: int) -> None:
        # Choosing how much pause to keep means wanting the pauses trimmed.
        self.player.set_keep_pause(steps * KEEP_STEP_MS)
        self.player.set_skip_silence(True)


class SilenceButton(QToolButton):
    def __init__(self, player: Player) -> None:
        super().__init__(objectName="silenceButton")
        self.player = player
        self.setText(strings.PLAYER_SILENCE)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(ICON_SIZE - 2, ICON_SIZE - 2))
        self.popup = SilencePopup(player, self)
        self.clicked.connect(lambda: self.popup.show_under(self))
        player.silence_changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        on = self.player.skip_silence
        if self.property("active") != on:
            self.setProperty("active", on)
            _repolish(self)
        self.setToolTip(
            strings.PLAYER_SILENCE_TOOLTIP_ON.format(keep=seconds_label(self.player.keep_pause_ms))
            if on
            else strings.PLAYER_SILENCE_TOOLTIP_OFF
        )
        self._paint_icon()

    def _paint_icon(self) -> None:
        role = (
            QPalette.ColorRole.HighlightedText  # ink on the accent fill
            if self.player.skip_silence
            else QPalette.ColorRole.ButtonText
        )
        self.setIcon(silence_icon(self.palette().color(role)))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icon()
        super().changeEvent(event)
