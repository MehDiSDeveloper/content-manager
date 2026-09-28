"""Player panel: waveform + transport (−10 s, play/pause, +10 s), clock, speed and pause trimming.

The shared `Player` (audio engine facade) is owned by the main window; this widget shows
whichever voice is open and drives the player for it.
"""

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import SPEEDS, Player, PlayerState
from podcast_workspace.audio.silence import find_pauses
from podcast_workspace.audio.waveform import (
    ExtractionCancelledError,
    Waveform,
    extract,
    needs_seek_cache,
)
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.icons import ICON_SIZE, pause_icon, play_icon, skip_icon
from podcast_workspace.ui.player.silence_control import SilenceButton
from podcast_workspace.ui.player.waveform_view import WaveformView
from podcast_workspace.ui.support import format_clock, local_digits

SKIP_MS = 10_000


def install_player_keys(
    page: QWidget,
    player: Player,
    extra: tuple[tuple[str, Callable[[], None]], ...] = (),
    enabled: Callable[[], bool] = lambda: True,
) -> None:
    """Player keys that work anywhere on `page`. A focused line edit keeps Space, arrows
    and printable keys for itself (Qt gives it first claim through ShortcutOverride).
    `enabled` says whether the player is what the page shows right now; while it is not,
    the keys do nothing (Space still presses a focused button)."""

    def space() -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton):
            focus.animateClick()  # Space still presses a focused button
        elif enabled():
            player.toggle()

    def only_when_enabled(handler: Callable[[], None]) -> Callable[[], None]:
        return lambda: handler() if enabled() else None

    bindings: tuple[tuple[str, Callable[[], None]], ...] = (
        ("Space", space),
        ("Ctrl+Space", player.toggle),
        ("Right", lambda: player.skip(SKIP_MS)),
        ("Left", lambda: player.skip(-SKIP_MS)),
        ("-", lambda: player.step_speed(-1)),
        ("=", lambda: player.step_speed(1)),
        ("+", lambda: player.step_speed(1)),
        *extra,
    )
    context = Qt.ShortcutContext.WidgetWithChildrenShortcut
    for keys, handler in bindings:
        guarded = handler if keys == "Space" else only_when_enabled(handler)
        QShortcut(QKeySequence(keys), page, activated=guarded, context=context)


def speed_label(speed: float) -> str:
    return local_digits(f"{speed:g}").replace(".", strings.DECIMAL_SEPARATOR) + "×"


class _WaveformLoader(QObject):
    """Runs waveform extraction (and pause detection) on a plain thread; results arrive on
    the GUI thread."""

    progress = Signal(int, object)
    done = Signal(int, object, object)  # token, Waveform, pauses
    failed = Signal(int, str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()
        self._token = 0

    def start(self, path: Path) -> int:
        self._cancel.set()
        self._cancel = threading.Event()
        self._token += 1
        token, cancel = self._token, self._cancel

        def work() -> None:
            try:
                waveform = extract(path, cancel, lambda w: self.progress.emit(token, w))
                pauses = find_pauses(waveform)
            except ExtractionCancelledError:
                return
            except Exception as exc:  # reported to the GUI thread, never swallowed
                self.failed.emit(token, str(exc))
                return
            self.done.emit(token, waveform, pauses)

        threading.Thread(target=work, name="waveform", daemon=True).start()
        return token

    def cancel(self) -> None:
        self._cancel.set()
        self._token += 1

    def current(self, token: int) -> bool:
        return token == self._token


class PlayerWidget(QFrame):
    exact_duration = Signal(int, int)  # voice_id, duration_ms

    def __init__(self, player: Player) -> None:
        super().__init__(objectName="playerPanel")
        self.player = player
        self._voice_id: int | None = None
        self._path: Path | None = None
        self._loader = _WaveformLoader(self)
        self._loader.progress.connect(self._on_wave_progress)
        self._loader.done.connect(self._on_wave_done)
        self._loader.failed.connect(self._on_wave_failed)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self.waveform = WaveformView()
        self.waveform.seek_requested.connect(self.player.seek)
        col.addWidget(self.waveform)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.clock = QLabel(format_clock(0), objectName="clock")
        self.clock.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row.addWidget(self.clock)
        row.addStretch(1)
        self.back = self._transport_button(strings.PLAYER_BACK_TOOLTIP)
        self.back.clicked.connect(lambda: self.player.skip(-SKIP_MS))
        row.addWidget(self.back)
        self.play = QPushButton(objectName="playButton")
        self.play.setToolTip(strings.PLAYER_PLAY_TOOLTIP)
        self.play.setIconSize(QSize(ICON_SIZE + 2, ICON_SIZE + 2))
        self.play.setFixedSize(48, 48)
        self.play.clicked.connect(self.player.toggle)
        row.addWidget(self.play)
        self.forward = self._transport_button(strings.PLAYER_FORWARD_TOOLTIP)
        self.forward.clicked.connect(lambda: self.player.skip(SKIP_MS))
        row.addWidget(self.forward)
        row.addStretch(1)
        self.speed = QToolButton(objectName="speedButton")
        self.speed.setToolTip(strings.PLAYER_SPEED_TOOLTIP)
        self.speed.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.speed)
        group = QActionGroup(menu)
        self._speed_actions: dict[float, QAction] = {}
        for value in SPEEDS:
            action = menu.addAction(speed_label(value))
            action.setCheckable(True)
            action.triggered.connect(lambda _c=False, v=value: self.player.set_speed(v))
            group.addAction(action)
            self._speed_actions[value] = action
        self.speed.setMenu(menu)
        row.addWidget(self.speed)
        self.silence = SilenceButton(player)
        row.addWidget(self.silence)
        self.total = QLabel(format_clock(0), objectName="muted")
        self.total.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row.addWidget(self.total)
        row_host = QFrame()
        row_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)  # media controls never mirror
        row_host.setLayout(row)
        col.addWidget(row_host)

        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)
        player.duration_changed.connect(self._on_duration)
        player.speed_changed.connect(self._on_speed)
        player.error.connect(self._on_error)
        player.silence_changed.connect(self._show_cuts)
        self._paint_icons()
        self._on_speed(player.speed)
        self._set_enabled(False)

    def _transport_button(self, tooltip: str) -> QPushButton:
        button = QPushButton(objectName="transportButton")
        button.setToolTip(tooltip)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setFixedSize(40, 40)
        return button

    # public -------------------------------------------------------------------------------
    @property
    def voice_id(self) -> int | None:
        return self._voice_id

    def is_current(self) -> bool:
        """The shared player is playing (or holding) this widget's voice."""
        return self._path is not None and self.player.source == str(self._path)

    def open_voice(self, voice_id: int, path: Path, duration_ms: int) -> None:
        if self._voice_id == voice_id and self.is_current():
            return
        self._voice_id = voice_id
        self._path = path
        self.waveform.set_waveform(None)
        self.waveform.set_duration(duration_ms)
        self.waveform.set_position(0)
        if not path.is_file():
            self._loader.cancel()
            self.player.unload()
            self.waveform.set_message(strings.VOICE_MISSING)
            self._set_enabled(False)
            return
        self.waveform.set_message(strings.PLAYER_LOADING)
        self._set_enabled(True)
        self.player.load(str(path), duration_ms)
        self._loader.start(path)

    def close_voice(self) -> None:
        self._loader.cancel()
        if self.is_current():
            self.player.unload()
        self._voice_id = None
        self._path = None
        self.waveform.set_waveform(None)
        self.waveform.set_message("")
        self._set_enabled(False)

    # player events ----------------------------------------------------------------------
    def _on_position(self, position_ms: int) -> None:
        if not self.is_current():
            return
        self.waveform.set_position(position_ms)
        self.clock.setText(format_clock(position_ms))

    def _on_state(self, state: PlayerState) -> None:
        self._paint_icons()
        self.play.setToolTip(
            strings.PLAYER_PAUSE_TOOLTIP
            if state is PlayerState.PLAYING
            else strings.PLAYER_PLAY_TOOLTIP
        )

    def _on_duration(self, duration_ms: int) -> None:
        if self.is_current():
            self.waveform.set_duration(duration_ms)
            self.total.setText(format_clock(duration_ms))

    def _on_speed(self, speed: float) -> None:
        self.speed.setText(speed_label(speed))
        action = self._speed_actions.get(speed)
        if action is not None:
            action.setChecked(True)

    def _on_error(self, message: str) -> None:
        if self.is_current():
            self.waveform.set_message(strings.PLAYER_ERROR.format(error=message[:200]))

    # waveform ---------------------------------------------------------------------------
    def _on_wave_progress(self, token: int, waveform: Waveform) -> None:
        if self._loader.current(token):
            self.waveform.set_waveform(waveform)

    def _on_wave_done(self, token: int, waveform: Waveform, pauses: tuple) -> None:
        if not self._loader.current(token):
            return
        self.waveform.set_message("")
        self.waveform.set_waveform(waveform)
        if self._path is not None and needs_seek_cache(self._path):
            self.player.seek_cache_ready()
        if waveform.duration_ms > 0 and self._voice_id is not None:
            self.player.set_exact_duration(waveform.duration_ms)
            self.exact_duration.emit(self._voice_id, waveform.duration_ms)
        if self._path is not None:  # after the exact duration: trailing silence ends there
            self.player.set_pauses(str(self._path), pauses)

    def _show_cuts(self) -> None:
        """Shade what playback skips, following the slider as it moves."""
        skipping = self.is_current() and self.player.skip_silence
        self.waveform.set_cuts(self.player.silence_cuts() if skipping else ())

    def _on_wave_failed(self, token: int, message: str) -> None:
        if self._loader.current(token):
            self.waveform.set_message(strings.PLAYER_ERROR.format(error=message[:200]))

    # look -------------------------------------------------------------------------------
    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.back, self.play, self.forward, self.speed, self.silence):
            widget.setEnabled(enabled)
        if not enabled:
            self.clock.setText(format_clock(0))
            self.total.setText(format_clock(0))

    def _paint_icons(self) -> None:
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.ButtonText)
        on_accent = palette.color(QPalette.ColorRole.HighlightedText)
        playing = self.is_current() and self.player.is_playing
        self.play.setIcon(pause_icon(on_accent) if playing else play_icon(on_accent))
        self.back.setIcon(skip_icon(text, forward=False, label=local_digits(10)))
        self.forward.setIcon(skip_icon(text, forward=True, label=local_digits(10)))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icons()
        super().changeEvent(event)
