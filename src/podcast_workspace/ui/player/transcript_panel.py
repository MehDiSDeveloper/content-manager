"""Transcript tab under the player: run/cancel transcription, read the segments, click to seek.

Transcription runs on the thread pool; TranscriptionJobs relays progress to the GUI thread.
One job at a time (the service serializes anyway; faster-whisper saturates the CPU), with
a queue behind it for transcribing every voice that has no transcript yet.
"""

import bisect
import threading
import time
from collections import deque
from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Transcript, TranscriptSegment
from podcast_workspace.domain.text import find_spans, query_terms
from podcast_workspace.services.transcription import (
    ModelMissingError,
    TranscriptionCancelledError,
    TranscriptionUnavailableError,
)
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.player_widget import PlayerWidget
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    describe_error,
    format_clock,
    format_datetime,
    local_digits,
    run_async,
)

USER_SCROLL_GRACE_S = 4.0


class TranscriptionJobs(QObject):
    """App-wide runner. Signals carry the voice id so any panel can filter.

    Behind the running job there can be a queue («transcribe all»): each voice starts when
    the one before it ends, however it ended. Cancelling the running job skips just that
    voice; `stop()` drops the rest too. A missing model or library stops the queue, since
    every voice after it would fail the same way.
    """

    progress = Signal(int, float)
    finished = Signal(int)
    failed = Signal(int, str)  # voice id, message ("" = cancelled)
    queue_changed = Signal()
    batch_ended = Signal(str)  # what to tell the user: done, stopped, or why it could not go on
    _relay_progress = Signal(int, float)

    def __init__(self, workspace: Workspace, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._cancel: threading.Event | None = None
        self.running: int | None = None
        self.fraction = -1.0  # of the running job; -1 while it is preparing
        self._queue: deque[int] = deque()
        self._from_queue = False  # the running job is part of the batch
        self.batch_total = 0  # voices queued since the queue was last empty
        self.batch_done = 0  # of those, ended one way or another
        self.batch_ok = 0  # of those, transcribed
        self._relay_progress.connect(self.progress)  # queued: emitted on a worker thread
        self.progress.connect(self._track)

    @property
    def batching(self) -> bool:
        return self.batch_total > 0

    def is_queued(self, voice_id: int) -> bool:
        return voice_id in self._queue

    def enqueue(self, voice_ids: Iterable[int]) -> int:
        """Add voices to the queue, skipping ones already in it; returns how many."""
        added = [v for v in dict.fromkeys(voice_ids) if v != self.running and v not in self._queue]
        self._queue.extend(added)
        self.batch_total += len(added)
        if added:
            self.queue_changed.emit()
            self._next()
        return len(added)

    def stop(self) -> None:
        """Drop the queue and cancel the running job."""
        self.cancel()
        if self.batching:
            self._end_batch(stopped=True)

    def drop(self, voice_ids: Iterable[int]) -> None:
        """The voices are gone (deleted forever): out of the queue, and the running job
        cancelled if it is one of them."""
        gone = set(voice_ids)
        kept = [v for v in self._queue if v not in gone]
        removed = len(self._queue) - len(kept)
        if removed:
            self._queue = deque(kept)
            self.batch_total -= removed
            self.queue_changed.emit()
        if self.running in gone:
            self.cancel()

    def start(self, voice_id: int) -> bool:
        if self.running is not None:
            return False
        self._run(voice_id)
        return True

    def _run(self, voice_id: int) -> None:
        self.running = voice_id
        cancel = self._cancel = threading.Event()
        emit = self._relay_progress.emit

        def work() -> object:
            return self._ws.transcripts.transcribe(voice_id, lambda f: emit(voice_id, f), cancel)

        run_async(work, lambda _r: self._done(voice_id), lambda e: self._fail(voice_id, e))
        self.progress.emit(voice_id, -1.0)  # -1: preparing (model load, decode)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def _track(self, _voice_id: int, fraction: float) -> None:
        self.fraction = fraction

    def _next(self) -> None:
        if self.running is not None:
            return
        if self._queue:
            self._from_queue = True
            self._run(self._queue.popleft())
            self.queue_changed.emit()
        elif self.batching:
            self._end_batch()

    def _end_batch(self, fatal: str = "", stopped: bool = False) -> None:
        template = strings.TR_ALL_STOPPED if stopped else strings.TR_ALL_DONE
        message = fatal or template.format(
            ok=local_digits(self.batch_ok), total=local_digits(self.batch_total)
        )
        self._queue.clear()
        self._from_queue = False  # a job still winding down no longer counts
        self.batch_total = self.batch_done = self.batch_ok = 0
        self.queue_changed.emit()
        self.batch_ended.emit(message)

    def _ended(self, ok: bool, fatal: str = "") -> None:
        """Book-keeping after any job; then the next voice in the queue, if any."""
        self.running = None
        self.fraction = -1.0
        if self._from_queue:
            self._from_queue = False
            self.batch_done += 1
            self.batch_ok += ok
        if fatal and self.batching:
            self._end_batch(fatal)
        else:
            self._next()

    def _done(self, voice_id: int) -> None:
        self._ended(True)
        self.finished.emit(voice_id)

    def _fail(self, voice_id: int, exc: BaseException) -> None:
        fatal = ""
        match exc:
            case TranscriptionCancelledError():
                message = ""
            case TranscriptionUnavailableError():
                message = fatal = strings.TR_NOT_INSTALLED
            case ModelMissingError():
                message = fatal = strings.TR_MODEL_MISSING
            case FileNotFoundError():
                message = strings.TR_FILE_MISSING
            case _:
                message = strings.TR_FAILED.format(error=describe_error(exc))
        self._ended(False, fatal)
        self.failed.emit(voice_id, message)


class _SegmentRow(QFrame):
    activated = Signal(int)  # position ms
    move_focus = Signal(int, int)  # index, direction

    def __init__(self, index: int, segment: TranscriptSegment) -> None:
        super().__init__(objectName="noteRow")
        self.index = index
        self.segment = segment
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("active", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(12)
        time_button = QToolButton(objectName="gotoButton")
        time_button.setText(format_clock(segment.start_ms))
        time_button.setToolTip(strings.TR_GOTO_TOOLTIP)
        time_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        time_button.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        time_button.setCursor(Qt.CursorShape.PointingHandCursor)
        time_button.clicked.connect(lambda: self.activated.emit(self.segment.start_ms))
        row.addWidget(time_button, 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel(segment.text, objectName="noteText")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(text, 1)

    def set_active(self, active: bool) -> None:
        if self.property("active") != active:
            self.setProperty("active", active)
            self.style().unpolish(self)
            self.style().polish(self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.segment.start_ms)
        elif event.key() == Qt.Key.Key_Down:
            self.move_focus.emit(self.index, 1)
        elif event.key() == Qt.Key.Key_Up:
            self.move_focus.emit(self.index, -1)
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.activated.emit(self.segment.start_ms)


class TranscriptPanel(QFrame):
    settings_requested = Signal()
    changed = Signal(int)  # voice id whose transcript was (re)written

    def __init__(
        self,
        workspace: Workspace,
        events: AppEvents,
        player: PlayerWidget,
        jobs: TranscriptionJobs,
    ) -> None:
        super().__init__(objectName="transcriptPanel")
        self._ws = workspace
        self._events = events
        self._player = player
        self._jobs = jobs
        self._voice_id: int | None = None
        self._transcript: Transcript | None = None
        self._rows: list[_SegmentRow] = []
        self._starts: list[int] = []
        self._active: int | None = None
        self._last_user_scroll = 0.0

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        header = QHBoxLayout()
        self.meta = QLabel(objectName="muted")
        header.addWidget(self.meta, 1)
        self.copy_button = QPushButton(strings.TR_COPY, objectName="flatButton")
        self.copy_button.clicked.connect(self._copy)
        header.addWidget(self.copy_button)
        self.cancel_button = QPushButton(strings.TR_CANCEL)
        self.cancel_button.clicked.connect(jobs.cancel)
        header.addWidget(self.cancel_button)
        self.run_button = QPushButton(strings.TR_RUN)
        self.run_button.setToolTip(strings.TR_RUN_TOOLTIP)
        self.run_button.clicked.connect(self._run)
        header.addWidget(self.run_button)
        col.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        col.addWidget(self.progress)

        self.body = QStackedWidget()
        hint_page = QWidget()
        hint_col = QVBoxLayout(hint_page)
        hint_col.setContentsMargins(0, 8, 0, 0)
        self.hint = QLabel(objectName="muted")
        self.hint.setWordWrap(True)
        hint_col.addWidget(self.hint)
        self.settings_button = QPushButton(strings.TR_OPEN_SETTINGS, objectName="flatButton")
        self.settings_button.clicked.connect(self.settings_requested)
        hint_col.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignLeading)
        hint_col.addStretch(1)
        self.body.addWidget(hint_page)

        self.scroll = QScrollArea(objectName="noteScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.verticalScrollBar().sliderPressed.connect(self._user_scrolled)
        self.scroll.viewport().installEventFilter(self)
        self.host = QWidget(objectName="noteHost")
        self.rows_layout = QVBoxLayout(self.host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.host)
        self.body.addWidget(self.scroll)
        col.addWidget(self.body, 1)

        jobs.progress.connect(self._on_progress)
        jobs.finished.connect(self._on_finished)
        jobs.failed.connect(self._on_failed)
        jobs.queue_changed.connect(self._sync_controls)
        player.player.position_changed.connect(self._on_position)
        self._sync_controls()

    # public ----------------------------------------------------------------------------
    def set_voice(self, voice_id: int | None) -> None:
        self._voice_id = voice_id
        self._reload()

    def highlight_query(self, query: str) -> None:
        """Search hit: focus the first segment containing the query terms."""
        terms = query_terms(query)
        for row in self._rows:
            if terms and find_spans(row.segment.text, terms):
                self.scroll.ensureWidgetVisible(row)
                row.setFocus()
                return

    # data ------------------------------------------------------------------------------
    def _reload(self) -> None:
        for row in self._rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        self._starts = []
        self._active = None
        self._transcript = None
        if self._voice_id is not None:
            try:
                self._transcript = self._ws.transcripts.get(self._voice_id)
            except Exception:
                self._transcript = None
        if self._transcript is not None:
            self.host.setUpdatesEnabled(False)
            for index, segment in enumerate(self._transcript.segments):
                row = _SegmentRow(index, segment)
                row.activated.connect(self._seek)
                row.move_focus.connect(self._move_focus)
                self.rows_layout.insertWidget(index, row)
                self._rows.append(row)
            self.host.setUpdatesEnabled(True)
            self._starts = [s.start_ms for s in self._transcript.segments]
        self._show_state()

    def _show_state(self, message: str | None = None) -> None:
        transcript = self._transcript
        self.settings_button.hide()
        if message:
            self.hint.setText(message)
            self.settings_button.setVisible(message == strings.TR_MODEL_MISSING)
            self.body.setCurrentIndex(0)
        elif transcript is None:
            self.hint.setText(strings.TR_EMPTY)
            self.body.setCurrentIndex(0)
        elif not transcript.segments:
            self.hint.setText(strings.TR_NO_SPEECH)
            self.body.setCurrentIndex(0)
        else:
            self.body.setCurrentIndex(1)
        if transcript is not None:
            self.meta.setText(
                strings.TR_META.format(
                    n=local_digits(len(transcript.segments)),
                    model=transcript.model,
                    when=format_datetime(transcript.created_at),
                )
            )
        else:
            self.meta.setText("")
        self._sync_controls()

    def _sync_controls(self) -> None:
        running = self._jobs.running
        mine = running is not None and running == self._voice_id
        self.run_button.setText(strings.TR_RERUN if self._transcript else strings.TR_RUN)
        self.run_button.setVisible(not mine)
        self.run_button.setEnabled(self._voice_id is not None and running is None)
        queued = self._voice_id is not None and self._jobs.is_queued(self._voice_id)
        self.run_button.setEnabled(self.run_button.isEnabled() and not queued)
        if queued:
            tip = strings.TR_QUEUED
        elif running is not None:
            tip = strings.TR_BUSY_ELSEWHERE
        else:
            tip = strings.TR_RUN_TOOLTIP
        self.run_button.setToolTip(tip)
        self.cancel_button.setVisible(mine)
        self.progress.setVisible(mine)
        self.copy_button.setVisible(bool(self._transcript and self._transcript.segments))

    # actions ---------------------------------------------------------------------------
    def _run(self) -> None:
        if self._voice_id is None:
            return
        if self._transcript is not None and not confirm(
            self, strings.TR_REPLACE_CONFIRM, strings.TR_REPLACE
        ):
            return
        if self._jobs.start(self._voice_id):
            self._sync_controls()

    def _copy(self) -> None:
        if self._transcript is not None:
            QGuiApplication.clipboard().setText(self._transcript.text)
            self.meta.setText(strings.TR_COPIED)

    def _seek(self, position_ms: int) -> None:
        if self._player.is_current():
            self._player.player.seek(position_ms)
            if not self._player.player.is_playing:
                self._player.player.play()

    def _move_focus(self, index: int, direction: int) -> None:
        target = index + direction
        if 0 <= target < len(self._rows):
            self._rows[target].setFocus()
            self.scroll.ensureWidgetVisible(self._rows[target])

    # job signals -----------------------------------------------------------------------
    def _on_progress(self, voice_id: int, fraction: float) -> None:
        if voice_id != self._voice_id:
            self._sync_controls()
            return
        self._sync_controls()
        if fraction < 0:
            self.progress.setRange(0, 0)  # busy indicator while the model loads
            self.meta.setText(strings.TR_LOADING_MODEL)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(fraction * 1000))
            self.meta.setText(strings.TR_RUNNING.format(percent=local_digits(int(fraction * 100))))

    def _on_finished(self, voice_id: int) -> None:
        self._events.data_changed.emit()
        self.changed.emit(voice_id)
        if voice_id == self._voice_id:
            self._reload()
        else:
            self._sync_controls()

    def _on_failed(self, voice_id: int, message: str) -> None:
        if voice_id != self._voice_id:
            self._sync_controls()
            return
        if message:
            self._show_state(message)
        else:
            self._show_state()

    # playhead --------------------------------------------------------------------------
    def _user_scrolled(self) -> None:
        self._last_user_scroll = time.monotonic()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            self._user_scrolled()
        return super().eventFilter(watched, event)

    def _on_position(self, position_ms: int) -> None:
        if not self._rows or not self._player.is_current() or self._transcript is None:
            return
        index = bisect.bisect_right(self._starts, position_ms) - 1
        if index >= 0 and position_ms >= self._transcript.segments[index].end_ms + 1500:
            index = -1  # in a pause between segments
        active = index if index >= 0 else None
        if active == self._active:
            return
        if self._active is not None and self._active < len(self._rows):
            self._rows[self._active].set_active(False)
        self._active = active
        if active is not None:
            row = self._rows[active]
            row.set_active(True)
            if self.isVisible() and time.monotonic() - self._last_user_scroll > USER_SCROLL_GRACE_S:
                self.scroll.ensureWidgetVisible(row, 0, 40)
