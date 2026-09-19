"""TimestampNote panel under the player: composer + notes in time order.

Composer: the note's position is captured when the user starts a note (Insert / Ctrl+Enter or
the first keystroke), not when they press Enter, so typing time does not shift it.
Activation: rows whose window contains the playhead are highlighted and scrolled into view.
"""

import time

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import PlayerState
from podcast_workspace.domain.activation import ActivationTracker
from podcast_workspace.domain.entities import TimestampNote
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.player_widget import PlayerWidget
from podcast_workspace.ui.support import AppEvents, confirm, fa_digits, format_clock, show_error

USER_SCROLL_GRACE_S = 4.0


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class _NoteRow(QFrame):
    goto = Signal(int)
    edit_done = Signal(int, str)
    delete = Signal(int)
    move_focus = Signal(int, int)  # note_id, direction

    def __init__(self, note: TimestampNote) -> None:
        super().__init__(objectName="noteRow")
        assert note.id is not None
        self.note = note
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("active", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(12)
        self.goto_button = QToolButton(objectName="gotoButton")
        self.goto_button.setToolTip(strings.TS_GOTO_TOOLTIP)
        self.goto_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the row itself takes focus
        self.goto_button.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.goto_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.goto_button.clicked.connect(lambda: self.goto.emit(self.note_id))
        row.addWidget(self.goto_button, 0, Qt.AlignmentFlag.AlignTop)
        self.text = QLabel(objectName="noteText")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(self.text, 1)
        self.editor = QLineEdit()
        self.editor.hide()
        self.editor.installEventFilter(self)
        row.addWidget(self.editor, 1)
        self.refresh(note)

    @property
    def note_id(self) -> int:
        assert self.note.id is not None
        return self.note.id

    def refresh(self, note: TimestampNote) -> None:
        self.note = note
        self.goto_button.setText("▶  " + format_clock(note.position_ms))
        self.text.setText(note.text)

    def set_active(self, active: bool) -> None:
        if self.property("active") != active:
            self.setProperty("active", active)
            _repolish(self)
            _repolish(self.goto_button)

    def start_edit(self) -> None:
        self.text.hide()
        self.editor.setText(self.note.text)
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _end_edit(self, save: bool) -> None:
        text = self.editor.text()
        self.editor.hide()
        self.text.show()
        self.setFocus()
        if save and text.strip() and text.strip() != self.note.text:
            self.edit_done.emit(self.note_id, text)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.editor:
            if event.type() == QEvent.Type.KeyPress:
                assert isinstance(event, QKeyEvent)
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._end_edit(save=True)
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self._end_edit(save=False)
                    return True
            elif event.type() == QEvent.Type.FocusOut and self.editor.isVisible():
                self._end_edit(save=True)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.goto.emit(self.note_id)
        elif key == Qt.Key.Key_F2:
            self.start_edit()
        elif key == Qt.Key.Key_Delete:
            self.delete.emit(self.note_id)
        elif key == Qt.Key.Key_Up:
            self.move_focus.emit(self.note_id, -1)
        elif key == Qt.Key.Key_Down:
            self.move_focus.emit(self.note_id, 1)
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.start_edit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QEvent) -> None:  # type: ignore[override]
        menu = QMenu(self)
        menu.addAction(strings.TS_GOTO_TOOLTIP, lambda: self.goto.emit(self.note_id))
        menu.addAction(strings.TS_EDIT, self.start_edit)
        menu.addAction(strings.TS_DELETE, lambda: self.delete.emit(self.note_id))
        menu.exec(event.globalPos())  # type: ignore[attr-defined]


class _Composer(QLineEdit):
    started = Signal()  # first keystroke of a note: capture the position now
    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        if not self.text() and event.text().strip():
            self.started.emit()
        super().keyPressEvent(event)


class TimestampPanel(QFrame):
    def __init__(self, workspace: Workspace, events: AppEvents, player: PlayerWidget) -> None:
        super().__init__(objectName="timestampPanel")
        self._ws = workspace
        self._events = events
        self._player = player
        self._voice_id: int | None = None
        self._rows: dict[int, _NoteRow] = {}
        self._tracker = ActivationTracker()
        self._captured: int | None = None
        self._last_user_scroll = 0.0

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(QLabel(strings.TS_TITLE, objectName="sectionTitle"))
        header.addStretch(1)
        self.count = QLabel(objectName="muted")
        header.addWidget(self.count)
        col.addLayout(header)

        composer = QHBoxLayout()
        composer.setSpacing(8)
        self.capture = QToolButton(objectName="captureChip")
        self.capture.setToolTip(strings.TS_CAPTURE_TOOLTIP)
        self.capture.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.capture.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.capture.clicked.connect(self._recapture)
        composer.addWidget(self.capture)
        self.input = _Composer(objectName="noteComposer")
        self.input.setPlaceholderText(strings.TS_PLACEHOLDER)
        self.input.started.connect(self._on_started)
        self.input.cancelled.connect(self._cancel_note)
        self.input.returnPressed.connect(self._add_note)
        composer.addWidget(self.input, 1)
        self.add_button = QPushButton(strings.TS_ADD)
        self.add_button.clicked.connect(self._add_note)
        composer.addWidget(self.add_button)
        col.addLayout(composer)

        self.scroll = QScrollArea(objectName="noteScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().installEventFilter(self)
        host = QWidget(objectName="noteHost")
        self.rows_layout = QVBoxLayout(host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        self.empty = QLabel(strings.TS_EMPTY, objectName="muted")
        self.empty.setWordWrap(True)
        self.rows_layout.addWidget(self.empty)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(host)
        col.addWidget(self.scroll, 1)

        player.player.position_changed.connect(self._on_position)
        player.player.state_changed.connect(self._on_player_state)
        self._update_capture_chip()

    # public -------------------------------------------------------------------------------
    def set_voice(self, voice_id: int | None) -> None:
        self._voice_id = voice_id
        self._captured = None
        self.input.clear()
        self._reload()
        enabled = voice_id is not None
        self.input.setEnabled(enabled)
        self.add_button.setEnabled(enabled)

    def begin_note(self) -> None:
        """Insert / Ctrl+Enter: capture the playhead now and put the cursor in the composer."""
        if self._voice_id is None:
            return
        self._capture_now()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def focus_note(self, note_id: int) -> None:
        row = self._rows.get(note_id)
        if row is not None:
            self.scroll.ensureWidgetVisible(row)
            row.setFocus()

    # notes ------------------------------------------------------------------------------
    def _reload(self, focus_id: int | None = None) -> None:
        for row in self._rows.values():
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows.clear()
        notes: list[TimestampNote] = []
        if self._voice_id is not None:
            try:
                notes = self._ws.timestamp_notes.list_for_voice(self._voice_id)
            except Exception as exc:
                show_error(self, exc)
        for index, note in enumerate(notes):
            row = _NoteRow(note)
            row.goto.connect(self._goto)
            row.edit_done.connect(self._edit)
            row.delete.connect(self._delete)
            row.move_focus.connect(self._move_focus)
            self.rows_layout.insertWidget(index, row)
            self._rows[row.note_id] = row
        self.empty.setVisible(not notes and self._voice_id is not None)
        self.count.setText(strings.TS_COUNT.format(n=fa_digits(len(notes))) if notes else "")
        pairs = [(n.id, n.position_ms) for n in notes if n.id is not None]
        self._tracker.set_notes(pairs)
        self._tracker.reset()
        self._player.waveform.set_markers(pairs)
        self._player.waveform.set_active(frozenset())
        if self._player.is_current():
            self._apply(self._player.player.position, scroll=False)
        if focus_id is not None:
            self.focus_note(focus_id)

    def _ordered_ids(self) -> list[int]:
        rows = sorted(self._rows.values(), key=lambda r: (r.note.position_ms, r.note_id))
        return [r.note_id for r in rows]

    def _goto(self, note_id: int) -> None:
        row = self._rows.get(note_id)
        if row is not None and self._player.is_current():
            self._player.player.seek(row.note.position_ms)

    def _edit(self, note_id: int, text: str) -> None:
        try:
            note = self._ws.timestamp_notes.edit(note_id, text)
        except Exception as exc:
            show_error(self, exc)
            return
        row = self._rows.get(note_id)
        if row is not None:
            row.refresh(note)
        self._events.data_changed.emit()

    def _delete(self, note_id: int) -> None:
        row = self._rows.get(note_id)
        if row is None or not confirm(
            self, strings.TS_DELETE_CONFIRM.format(text=row.note.text[:60])
        ):
            return
        ids = self._ordered_ids()
        index = ids.index(note_id)
        neighbour = ids[index + 1] if index + 1 < len(ids) else (ids[index - 1] if index else None)
        try:
            self._ws.timestamp_notes.delete(note_id)
        except Exception as exc:
            show_error(self, exc)
        self._events.data_changed.emit()
        self._reload(focus_id=neighbour)

    def _move_focus(self, note_id: int, direction: int) -> None:
        ids = self._ordered_ids()
        index = ids.index(note_id) + direction
        if 0 <= index < len(ids):
            self.focus_note(ids[index])
        elif index < 0:
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    # composer ---------------------------------------------------------------------------
    def _position_now(self) -> int:
        return self._player.player.position if self._player.is_current() else 0

    def _capture_now(self) -> None:
        self._captured = self._position_now()
        self._update_capture_chip()

    def _on_started(self) -> None:
        if self._captured is None:
            self._capture_now()

    def _recapture(self) -> None:
        self._capture_now()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _cancel_note(self) -> None:
        self.input.clear()
        self._captured = None
        self._update_capture_chip()
        self._player.waveform.setFocus()

    def _add_note(self) -> None:
        text = self.input.text()
        if self._voice_id is None or not text.strip():
            return
        position = self._captured if self._captured is not None else self._position_now()
        try:
            note = self._ws.timestamp_notes.add(self._voice_id, position, text)
        except Exception as exc:
            show_error(self, exc)
            return
        self.input.clear()
        self._captured = None
        self._update_capture_chip()
        self._events.data_changed.emit()
        self._reload()
        if note.id is not None and note.id in self._rows:
            self.scroll.ensureWidgetVisible(self._rows[note.id])

    def _update_capture_chip(self) -> None:
        frozen = self._captured is not None
        shown = self._captured if frozen else self._position_now()
        self.capture.setText(format_clock(shown or 0))
        if self.capture.property("captured") != frozen:
            self.capture.setProperty("captured", frozen)
            _repolish(self.capture)

    # activation -------------------------------------------------------------------------
    def _on_position(self, position_ms: int) -> None:
        if self._voice_id is None or not self._player.is_current():
            return
        if self._captured is None:
            self.capture.setText(format_clock(position_ms))
        self._apply(position_ms, scroll=True)

    def _on_player_state(self, state: PlayerState) -> None:
        if state in (PlayerState.EMPTY, PlayerState.ERROR) or not self._player.is_current():
            for note_id in self._tracker.reset().left:
                row = self._rows.get(note_id)
                if row is not None:
                    row.set_active(False)
            self._player.waveform.set_active(frozenset())

    def _apply(self, position_ms: int, scroll: bool) -> None:
        change = self._tracker.update(position_ms)
        if change.entered or change.left:
            self._player.waveform.set_active(change.active)
        for note_id in change.left:
            row = self._rows.get(note_id)
            if row is not None:
                row.set_active(False)
        for note_id in change.entered:
            row = self._rows.get(note_id)
            if row is not None:
                row.set_active(True)
        if scroll and change.entered and self._may_autoscroll():
            latest = max(change.entered, key=lambda i: self._rows[i].note.position_ms)
            self.scroll.ensureWidgetVisible(self._rows[latest], 0, 24)

    def _may_autoscroll(self) -> bool:
        if time.monotonic() - self._last_user_scroll < USER_SCROLL_GRACE_S:
            return False
        return not any(row.editor.isVisible() for row in self._rows.values())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            self._last_user_scroll = time.monotonic()
        return super().eventFilter(watched, event)
