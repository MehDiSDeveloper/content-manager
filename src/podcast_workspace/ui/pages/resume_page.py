"""Startup screen: where you left off. One primary action: Continue."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from podcast_workspace.services.content_services import ResumeInfo
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.episode_workspace import note_label, stale_text
from podcast_workspace.ui.support import format_datetime

CARD_WIDTH = 580
SNIPPET_CHARS = 280


class ResumePage(QWidget):
    continue_requested = Signal(int, object)  # episode_id, note_id | None
    skip_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._info: ResumeInfo | None = None
        outer = QVBoxLayout(self)
        outer.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame(objectName="resumeCard")
        card.setFixedWidth(CARD_WIDTH)
        col = QVBoxLayout(card)
        col.setContentsMargins(36, 32, 36, 32)
        col.setSpacing(8)
        col.addWidget(QLabel(strings.RESUME_EYEBROW, objectName="eyebrow"))
        self.title = QLabel(objectName="resumeTitle")
        self.title.setWordWrap(True)
        col.addWidget(self.title)
        self.meta = QLabel(objectName="muted")
        col.addWidget(self.meta)
        col.addSpacing(14)
        col.addWidget(QLabel(strings.RESUME_NEXT_ACTION, objectName="fieldLabel"))
        self.next_action = QLabel(objectName="resumeNext")
        self.next_action.setWordWrap(True)
        col.addWidget(self.next_action)
        col.addSpacing(12)
        col.addWidget(QLabel(strings.RESUME_LAST_NOTE, objectName="fieldLabel"))
        self.note_title = QLabel(objectName="resumeNoteTitle")
        self.note_title.setWordWrap(True)
        col.addWidget(self.note_title)
        self.note_body = QLabel(objectName="muted")
        self.note_body.setWordWrap(True)
        col.addWidget(self.note_body)
        col.addSpacing(22)
        buttons = QHBoxLayout()
        self.continue_button = QPushButton(strings.RESUME_CONTINUE, objectName="primary")
        self.continue_button.setMinimumWidth(160)
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self._continue)
        buttons.addWidget(self.continue_button)
        buttons.addStretch(1)
        skip = QPushButton(strings.RESUME_SKIP, objectName="flatButton")
        skip.clicked.connect(self.skip_requested.emit)
        buttons.addWidget(skip)
        col.addLayout(buttons)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)

    def show_info(self, info: ResumeInfo) -> None:
        self._info = info
        episode = info.episode
        self.title.setText(episode.title)
        meta = [strings.STATUS_LABELS[episode.status]]
        badge = stale_text(episode)
        if badge:
            meta.append(badge)
        meta.append(strings.UPDATED_AT.format(when=format_datetime(episode.updated_at)))
        self.meta.setText("  ·  ".join(meta))
        self.next_action.setText(episode.next_action or strings.RESUME_NO_NEXT)
        note = info.note
        if note is None:
            self.note_title.setText(strings.RESUME_NO_NOTE)
            self.note_body.hide()
        else:
            self.note_title.setText(note_label(note))
            body = note.body.strip()
            if len(body) > SNIPPET_CHARS:
                body = body[:SNIPPET_CHARS].rstrip() + "…"
            self.note_body.setText(body)
            self.note_body.setVisible(bool(body))

    def focus_main(self) -> None:
        self.continue_button.setFocus()

    def _continue(self) -> None:
        if self._info is not None and self._info.episode.id is not None:
            note_id = self._info.note.id if self._info.note is not None else None
            self.continue_requested.emit(self._info.episode.id, note_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._continue()
        elif event.key() == Qt.Key.Key_Escape:
            self.skip_requested.emit()
        else:
            super().keyPressEvent(event)
