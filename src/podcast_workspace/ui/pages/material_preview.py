"""One linked (or suggested) item, shown inside the episode workspace's materials panel.

The point is to write with the material in view: an audio idea plays, and its transcript
follows along, right beside the note being written; a text idea is there to read and copy
from. Nothing here edits the item — «Open in Ideas» is the way to its tags, its text and
its timestamp notes — so the preview can stay small and the note keeps the attention.

The panel turns into the preview instead of a new column opening: the frame of the page
stays what it was, and the arrow at the top (or Esc) turns it back into the list.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import IdeaNote, Voice
from podcast_workspace.domain.smart_links import LinkKind
from podcast_workspace.services.content_services import ItemRef
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.player_widget import PlayerWidget, install_player_keys
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs, TranscriptPanel
from podcast_workspace.ui.support import AppEvents, format_datetime, format_duration


class MaterialPreview(QWidget):
    back_requested = Signal()
    open_requested = Signal(object, int)  # LinkKind, item id: to the Ideas page
    link_requested = Signal(object, int)  # LinkKind, item id: a suggestion, linked from here
    settings_requested = Signal()  # the transcript's «transcription settings»

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
        super().__init__()
        self._ws = workspace
        self.item: ItemRef | None = None
        self._voice: Voice | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.back = QToolButton(objectName="backButton", text=strings.WS_PREVIEW_BACK)
        self.back.setToolTip(strings.WS_PREVIEW_BACK_TOOLTIP)
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.back_requested)
        head.addWidget(self.back)
        head.addStretch(1)
        self.open_button = QPushButton(strings.WS_PREVIEW_OPEN, objectName="flatButton")
        self.open_button.setToolTip(strings.WS_PREVIEW_OPEN_TOOLTIP)
        self.open_button.clicked.connect(self._open)
        head.addWidget(self.open_button)
        col.addLayout(head)

        self.title = QLabel(objectName="editorTitle")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.title)
        self.meta = QLabel(objectName="muted")
        self.meta.setWordWrap(True)
        col.addWidget(self.meta)

        self.body = QStackedWidget()
        # Read-only but selectable: copying a line into the note is the whole use of it.
        self.text = QPlainTextEdit(objectName="ideaText")
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.body.addWidget(self.text)
        self.voice_view = QWidget()
        voice_col = QVBoxLayout(self.voice_view)
        voice_col.setContentsMargins(0, 0, 0, 0)
        voice_col.setSpacing(12)
        self.player = PlayerWidget(player, compact=True)
        self.player.exact_duration.connect(self._store_exact_duration)
        voice_col.addWidget(self.player)
        self.transcript = TranscriptPanel(workspace, events, self.player, jobs)
        # The panel is narrow: the transcript's info line gives way to its buttons.
        self.transcript.meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.transcript.settings_requested.connect(self.settings_requested)
        voice_col.addWidget(self.transcript, 1)
        self.body.addWidget(self.voice_view)
        col.addWidget(self.body, 1)

        self.link_button = QPushButton(strings.WS_LINK, objectName="primary")
        self.link_button.setToolTip(strings.WS_LINK_TOOLTIP)
        self.link_button.clicked.connect(self._link)
        col.addWidget(self.link_button)

        # Player keys only while the caret is in the audio view: in the note, Space is
        # a space.
        install_player_keys(self.voice_view, player, enabled=lambda: self._voice is not None)
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape),
            self,
            activated=self.back_requested.emit,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )

    # public ----------------------------------------------------------------------------
    def show_item(self, kind: LinkKind, item_id: int, linked: bool) -> bool:
        """False when there is nothing to show (it went to the trash meanwhile)."""
        try:
            item = (
                self._ws.voices.get(item_id)
                if kind is LinkKind.VOICE
                else self._ws.ideas.get(item_id)
            )
        except Exception:
            return False
        if item.in_trash:
            return False
        self.item = (kind, item_id)
        tags = [t.name for t in self._ws.tags.by_ids(item.tag_ids)]
        if isinstance(item, Voice):
            self._show_voice(item, tags)
        else:
            self._show_text(item, tags)
        self.set_linked(linked)
        return True

    def close_item(self) -> None:
        self.item = None
        self._voice = None
        self.player.close_voice()
        self.transcript.set_voice(None)
        self.text.clear()

    def set_linked(self, linked: bool) -> None:
        """A suggestion shown here can be linked from here; a linked item needs nothing."""
        self.link_button.setVisible(not linked)

    def focus(self) -> None:
        if self._voice is not None:
            self.player.waveform.setFocus()
        else:
            self.text.setFocus()

    # showing ---------------------------------------------------------------------------
    def _show_voice(self, voice: Voice, tags: list[str]) -> None:
        assert voice.id is not None
        self._voice = voice
        self.title.setText(Path(voice.file_path).name)
        self.title.show()
        parts = [strings.KIND_VOICE, format_duration(voice.duration_ms), *self._badges(voice)]
        self.meta.setText(self._meta(parts, tags))
        self.text.clear()
        self.body.setCurrentWidget(self.voice_view)
        self.player.open_voice(voice.id, Path(voice.file_path), voice.duration_ms)
        self.transcript.set_voice(voice.id)

    def _show_text(self, idea: IdeaNote, tags: list[str]) -> None:
        if self._voice is not None:
            self._voice = None
            self.player.close_voice()
            self.transcript.set_voice(None)
        # The text itself follows, first line and all: a heading would only repeat it.
        self.title.hide()
        parts = [
            strings.KIND_IDEA,
            strings.UPDATED_AT.format(when=format_datetime(idea.updated_at)),
            *self._badges(idea),
        ]
        self.meta.setText(self._meta(parts, tags))
        self.text.setPlainText(idea.text)
        self.body.setCurrentWidget(self.text)

    @staticmethod
    def _badges(item: Voice | IdeaNote) -> list[str]:
        return [strings.ARCHIVED_BADGE] if item.archived else []

    @staticmethod
    def _meta(parts: list[str], tags: list[str]) -> str:
        if tags:
            parts = [*parts, strings.LIST_SEPARATOR.join(tags)]
        return "  ·  ".join(p for p in parts if p)

    # actions ---------------------------------------------------------------------------
    def _open(self) -> None:
        if self.item is not None:
            self.open_requested.emit(*self.item)

    def _link(self) -> None:
        if self.item is not None:
            self.link_requested.emit(*self.item)

    def _store_exact_duration(self, voice_id: int, duration_ms: int) -> None:
        try:
            self._ws.voices.set_duration(voice_id, duration_ms)
        except Exception:
            return  # informational only; the voice may have gone meanwhile

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Another page may have taken the shared player meanwhile: take it back, or the
        # play button here would drive someone else's recording.
        voice = self._voice
        if voice is not None and voice.id is not None and not self.player.is_current():
            self.player.open_voice(voice.id, Path(voice.file_path), voice.duration_ms)
