"""The publish checklist on the episode workspace: a chip that says how far along it is
(«Publish 2/5»), and a small panel under it to tick the rest off.

A chip and not a section of the page: for most of an episode's life the checklist is
nothing to look at, and at the end it is five ticks. The chip keeps it one glance and
one click away at every stage, and fills in once everything is done — the same look the
switches elsewhere use for "on".

Every tick is saved (and undoable) the moment it is made; «where it was published» is
saved as it is typed, one undo step per run of typing, like the other text fields.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Episode
from podcast_workspace.domain.publish import PublishChecklist, PublishStep
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.popup import PlayerPopup
from podcast_workspace.ui.support import local_digits, show_error

SAVE_DELAY_MS = 700
WHERE_LINES = 3


class _ChecklistPopup(PlayerPopup):
    saved = Signal(object)  # Episode

    def __init__(self, parent: QWidget, workspace: Workspace) -> None:
        super().__init__(parent, "publishPopup")
        self._ws = workspace
        self._episode_id: int | None = None
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 16)
        col.setSpacing(8)
        col.addWidget(QLabel(strings.PUBLISH_TITLE, objectName="panelTitle"))
        self.boxes: dict[PublishStep, QCheckBox] = {}
        for step in PublishStep:
            box = QCheckBox(strings.PUBLISH_STEPS[step.value])
            box.toggled.connect(lambda on, s=step: self._check(s, on))
            col.addWidget(box)
            self.boxes[step] = box
        col.addSpacing(4)
        col.addWidget(QLabel(strings.PUBLISH_WHERE, objectName="fieldLabel"))
        self.where = QPlainTextEdit()
        self.where.setPlaceholderText(strings.PUBLISH_WHERE_PLACEHOLDER)
        self.where.setTabChangesFocus(True)
        line = self.where.fontMetrics().lineSpacing()
        self.where.setFixedHeight(line * WHERE_LINES + 18)
        self.where.setMinimumWidth(300)
        self.where.textChanged.connect(self._schedule)
        col.addWidget(self.where)
        self._timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_where)
        self._loading = False

    def show_for(self, episode: Episode, anchor: QWidget) -> None:
        self._episode_id = episode.id
        self._loading = True
        for step, box in self.boxes.items():
            box.setChecked(step in episode.publish.done)
        self.where.setPlainText(episode.publish.where)
        self._loading = False
        self.show_under(anchor)
        next(iter(self.boxes.values())).setFocus()

    def _check(self, step: PublishStep, on: bool) -> None:
        if self._loading or self._episode_id is None:
            return
        self._flush()  # what was typed comes before the tick, in the undo history too
        try:
            self.saved.emit(self._ws.episodes.check_publish_step(self._episode_id, step, on))
        except Exception as exc:
            show_error(self, exc)

    def _schedule(self) -> None:
        if not self._loading:
            self._timer.start()

    def _flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._save_where()

    def _save_where(self) -> None:
        if self._episode_id is None:
            return
        try:
            episode = self._ws.episodes.set_published_where(
                self._episode_id, self.where.toPlainText()
            )
        except Exception as exc:
            show_error(self, exc)
            return
        self.saved.emit(episode)

    def hideEvent(self, event: QHideEvent) -> None:
        self._flush()
        super().hideEvent(event)


class PublishChecklistButton(QToolButton):
    saved = Signal(object)  # Episode, after any change to its checklist

    def __init__(self, workspace: Workspace) -> None:
        super().__init__(objectName="publishChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(strings.PUBLISH_TOOLTIP)
        self._episode: Episode | None = None
        self._popup = _ChecklistPopup(self, workspace)
        self._popup.saved.connect(self._on_saved)
        self.clicked.connect(self._open)
        self.show_checklist(PublishChecklist())

    def set_episode(self, episode: Episode) -> None:
        self._episode = episode
        self.show_checklist(episode.publish)

    def show_checklist(self, checklist: PublishChecklist) -> None:
        if checklist.is_complete:
            self.setText(strings.PUBLISH_CHIP_DONE)
        else:
            self.setText(
                strings.PUBLISH_CHIP.format(
                    done=local_digits(checklist.completed), total=local_digits(checklist.total)
                )
            )
        self.setProperty("complete", checklist.is_complete)
        self.style().unpolish(self)
        self.style().polish(self)

    def _open(self) -> None:
        if self._episode is not None:
            self._popup.show_for(self._episode, self)

    def _on_saved(self, episode: Episode) -> None:
        self.set_episode(episode)
        self.saved.emit(episode)
