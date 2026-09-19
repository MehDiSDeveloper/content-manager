"""Episodes, Voices and Ideas pages: create, list, edit (autosave), delete."""

import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QHideEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Episode, EpisodeStatus, IdeaNote, Voice
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import ListPage, Row
from podcast_workspace.ui.pages.episode_workspace import stale_text
from podcast_workspace.ui.player.player_widget import SKIP_MS, PlayerWidget
from podcast_workspace.ui.player.timestamp_panel import TimestampPanel
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs, TranscriptPanel
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    fa_digits,
    format_datetime,
    format_duration,
    run_async,
    show_error,
)
from podcast_workspace.ui.widgets.tag_input import TagInput

AUTOSAVE_DELAY_MS = 700


def _danger_button(text: str) -> QPushButton:
    return QPushButton(text, objectName="danger")


def _first_line(text: str, width: int = 70) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


class EpisodesPage(ListPage):
    open_workspace = Signal(int)

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__(strings.EPISODES_TITLE, strings.EPISODE_NEW, strings.EPISODE_EMPTY)
        self._ws = workspace
        self._events = events
        self._episode: Episode | None = None

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(18)
        self.title_edit = QLineEdit(objectName="titleEdit")
        self.title_edit.setPlaceholderText(strings.EPISODE_TITLE_PLACEHOLDER)
        self.title_edit.editingFinished.connect(self._save_fields)
        col.addWidget(self.title_edit)

        form = QFormLayout()
        form.setSpacing(12)
        self.status_box = QComboBox()
        for status in EpisodeStatus:
            self.status_box.addItem(strings.STATUS_LABELS[status], status)
        self.status_box.activated.connect(lambda _i: self._save_fields())
        form.addRow(strings.EPISODE_STATUS, self.status_box)
        self.next_action = QLineEdit(placeholderText=strings.EPISODE_NEXT_ACTION_PLACEHOLDER)
        self.next_action.editingFinished.connect(self._save_fields)
        form.addRow(strings.EPISODE_NEXT_ACTION, self.next_action)
        self.tag_input = TagInput(workspace.tags, events)
        self.tag_input.tags_changed.connect(self._save_tags)
        form.addRow(strings.TAG_LABEL, self.tag_input)
        col.addLayout(form)

        self.meta = QLabel(objectName="muted")
        col.addWidget(self.meta)
        col.addStretch(1)
        actions = QHBoxLayout()
        enter = QPushButton(strings.EPISODE_OPEN_WORKSPACE)
        enter.setToolTip("Ctrl+Enter")
        enter.clicked.connect(self._open_current)
        actions.addWidget(enter)
        actions.addStretch(1)
        delete = _danger_button(strings.DELETE)
        delete.clicked.connect(self._delete_current)
        actions.addWidget(delete)
        col.addLayout(actions)
        self.list.itemDoubleClicked.connect(lambda _i: self._open_current())
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._open_current)

    def _open_current(self) -> None:
        item_id = self.current_id()
        if item_id is not None:
            self.open_workspace.emit(item_id)

    def _row(self, episode: Episode) -> Row:
        assert episode.id is not None
        subtitle = strings.STATUS_LABELS[episode.status]
        badge = stale_text(episode)
        if badge:
            subtitle = badge + "  ·  " + subtitle
        if episode.next_action:
            subtitle += "  ·  " + episode.next_action
        return Row(episode.id, episode.title, subtitle)

    def rows(self) -> list[Row]:
        return [self._row(e) for e in self._ws.episodes.list_all()]

    def show_item(self, item_id: int) -> None:
        try:
            self._episode = self._ws.episodes.open(item_id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._fill(self._episode)

    def _fill(self, episode: Episode) -> None:
        self.title_edit.setText(episode.title)
        self.status_box.setCurrentIndex(self.status_box.findData(episode.status))
        self.next_action.setText(episode.next_action)
        self.tag_input.set_tag_ids(episode.tag_ids)
        self.meta.setText(
            strings.CREATED_AT.format(when=format_datetime(episode.created_at))
            + "     "
            + strings.UPDATED_AT.format(when=format_datetime(episode.updated_at))
        )

    def focus_editor(self) -> None:
        self.title_edit.setFocus()

    def _save_fields(self) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            saved = self._ws.episodes.update(
                episode.id,
                title=self.title_edit.text(),
                status=self.status_box.currentData(),
                next_action=self.next_action.text(),
            )
        except Exception as exc:
            show_error(self, exc)
            self._fill(episode)  # revert to the last good state
            return
        if saved.updated_at != episode.updated_at:
            self._episode = saved
            self._fill(saved)
            self.update_row(self._row(saved))
            self._events.data_changed.emit()

    def _save_tags(self, tag_ids: list[int]) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.set_tags(episode.id, tag_ids)
            self._events.data_changed.emit()
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(episode.tag_ids)

    def primary_action(self) -> None:
        try:
            episode = self._ws.episodes.create(strings.EPISODE_DEFAULT_TITLE)
        except Exception as exc:
            show_error(self, exc)
            return
        assert episode.id is not None
        self._events.data_changed.emit()
        self.refresh(select_id=episode.id)
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def delete_item(self, item_id: int) -> None:
        episode = self._episode
        title = episode.title if episode and episode.id == item_id else ""
        if not confirm(self, strings.EPISODE_DELETE_CONFIRM.format(title=title)):
            return
        try:
            self._ws.episodes.delete(item_id)
        except Exception as exc:
            show_error(self, exc)
        self._episode = None
        self._events.data_changed.emit()
        self.refresh()
        self.list.setFocus()


class VoicesPage(ListPage):
    TAB_NOTES, TAB_TRANSCRIPT = 0, 1
    settings_requested = Signal()

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
        super().__init__(strings.VOICES_TITLE, strings.VOICE_IMPORT, strings.VOICE_EMPTY)
        self._ws = workspace
        self._events = events
        self._voice: Voice | None = None
        self._pending_note: int | None = None
        self._transcribed: set[int] = set()
        self.setAcceptDrops(True)
        self.primary.setToolTip("Ctrl+N / Ctrl+O")

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        self.name = QLabel(objectName="editorTitle")
        self.name.setWordWrap(True)
        col.addWidget(self.name)
        self.path = QLabel(objectName="muted")
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.path)
        self.missing = QLabel(strings.VOICE_MISSING, objectName="warning")
        col.addWidget(self.missing)
        self.meta = QLabel(objectName="muted")
        col.addWidget(self.meta)

        form = QFormLayout()
        self.tag_input = TagInput(workspace.tags, events, limit=MAX_TAGS_PER_ITEM)
        self.tag_input.tags_changed.connect(self._save_tags)
        form.addRow(strings.TAG_LABEL, self.tag_input)
        col.addLayout(form)

        self.player = PlayerWidget(player)
        self.player.exact_duration.connect(self._store_exact_duration)
        col.addSpacing(6)
        col.addWidget(self.player)
        self.tabs = QTabBar(objectName="noteTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(strings.TR_TAB_NOTES)
        self.tabs.addTab(strings.TR_TAB_TRANSCRIPT)
        self.tabs.setToolTip("Ctrl+Tab")
        col.addWidget(self.tabs)
        self.panels = QStackedWidget()
        self.notes = TimestampPanel(workspace, events, self.player)
        self.notes.title.hide()  # the tab names it
        self.panels.addWidget(self.notes)
        self.transcript = TranscriptPanel(workspace, events, self.player, jobs)
        self.transcript.settings_requested.connect(self.settings_requested)
        self.transcript.changed.connect(self._on_transcript_changed)
        self.panels.addWidget(self.transcript)
        self.tabs.currentChanged.connect(self.panels.setCurrentIndex)
        col.addWidget(self.panels, 1)

        actions = QHBoxLayout()
        show = QPushButton(strings.VOICE_SHOW_IN_FOLDER)
        show.clicked.connect(self._show_in_folder)
        actions.addWidget(show)
        actions.addStretch(1)
        delete = _danger_button(strings.VOICE_DELETE)
        delete.clicked.connect(self._delete_current)
        actions.addWidget(delete)
        col.addLayout(actions)

        QShortcut(QKeySequence.StandardKey.Open, self, activated=self.primary_action)
        QShortcut(
            QKeySequence("Ctrl+Tab"),
            self,
            activated=lambda: self.tabs.setCurrentIndex(1 - self.tabs.currentIndex()),
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self._install_player_keys()

    def _install_player_keys(self) -> None:
        """Player keys work anywhere on this page. A focused line edit keeps Space, arrows and
        printable keys for itself (Qt gives it first claim through ShortcutOverride)."""
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        player = self.player.player
        bindings: list[tuple[str, Callable[[], None]]] = [
            ("Space", self._space),
            ("Ctrl+Space", player.toggle),
            ("Right", lambda: player.skip(SKIP_MS)),
            ("Left", lambda: player.skip(-SKIP_MS)),
            ("-", lambda: player.step_speed(-1)),
            ("=", lambda: player.step_speed(1)),
            ("+", lambda: player.step_speed(1)),
            ("Insert", self.notes.begin_note),
            ("Ctrl+Return", self.notes.begin_note),
        ]
        for keys, handler in bindings:
            QShortcut(QKeySequence(keys), self, activated=handler, context=context)

    def _space(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton):
            focus.animateClick()  # Space still presses a focused button
        else:
            self.player.player.toggle()

    def _row(self, voice: Voice) -> Row:
        assert voice.id is not None
        name = Path(voice.file_path).name
        parts = [format_duration(voice.duration_ms), voice.format.upper()]
        parts.append(format_datetime(voice.imported_at))
        if voice.id in self._transcribed:
            parts.append(strings.VOICE_HAS_TRANSCRIPT)
        return Row(voice.id, name, "  ·  ".join(p for p in parts if p))

    def rows(self) -> list[Row]:
        self._transcribed = self._ws.transcripts.voice_ids()
        return [self._row(v) for v in self._ws.voices.list_all()]

    def _on_transcript_changed(self, voice_id: int) -> None:
        self._transcribed.add(voice_id)
        try:
            self.update_row(self._row(self._ws.voices.get(voice_id)))
        except Exception:
            return  # removed meanwhile

    def open_transcript(self, voice_id: int, query: str) -> None:
        """Search hit on a transcript: open the voice on its transcript tab."""
        self.select(voice_id)
        self.tabs.setCurrentIndex(self.TAB_TRANSCRIPT)
        self.transcript.highlight_query(query)

    def external_change(self) -> None:
        """Items arrived from outside (Bale bot): refresh the list, keep the editor as is."""
        if self.isVisible():
            self.refresh(load=False)

    def show_item(self, item_id: int) -> None:
        try:
            voice = self._ws.voices.get(item_id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._voice = voice
        self.name.setText(Path(voice.file_path).name)
        self.path.setText(voice.file_path)
        self.missing.setVisible(not Path(voice.file_path).exists())
        self.meta.setText(self._meta_text(voice))
        self.tag_input.set_tag_ids(voice.tag_ids)
        assert voice.id is not None
        self.player.open_voice(voice.id, Path(voice.file_path), voice.duration_ms)
        self.notes.set_voice(voice.id)
        self.transcript.set_voice(voice.id)
        if self._pending_note is not None:
            self.tabs.setCurrentIndex(self.TAB_NOTES)
            self.notes.focus_note(self._pending_note)
            self._pending_note = None

    def clear_editor(self) -> None:
        self._voice = None
        self.player.close_voice()
        self.notes.set_voice(None)
        self.transcript.set_voice(None)

    def open_note(self, voice_id: int, note_id: int) -> None:
        """Search hit on a timestamp note: open its voice with that note focused."""
        self._pending_note = note_id
        self.select(voice_id)
        if self._pending_note is not None:
            self.tabs.setCurrentIndex(self.TAB_NOTES)
            self.notes.focus_note(note_id)
            self._pending_note = None

    def focus_editor(self) -> None:
        self.player.waveform.setFocus()

    def _meta_text(self, voice: Voice) -> str:
        return (
            f"{format_duration(voice.duration_ms)}  ·  {voice.format.upper()}  ·  "
            + strings.IMPORTED_AT.format(when=format_datetime(voice.imported_at))
        )

    def _store_exact_duration(self, voice_id: int, duration_ms: int) -> None:
        try:
            voice = self._ws.voices.set_duration(voice_id, duration_ms)
        except Exception:
            return  # informational only; the voice may have been removed meanwhile
        if self._voice is not None and self._voice.id == voice_id:
            self._voice = voice
            self.meta.setText(self._meta_text(voice))
        self.update_row(self._row(voice))

    def _save_tags(self, tag_ids: list[int]) -> None:
        voice = self._voice
        if voice is None or voice.id is None:
            return
        try:
            self._voice = self._ws.voices.set_tags(voice.id, tag_ids)
            self._events.data_changed.emit()
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(voice.tag_ids)

    def _show_in_folder(self) -> None:
        if self._voice is None:
            return
        path = Path(self._voice.file_path)
        if path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif path.parent.exists():
            subprocess.Popen(["explorer", str(path.parent)])

    def primary_action(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            strings.VOICE_IMPORT_DIALOG,
            "",
            strings.VOICE_IMPORT_FILTER.format(patterns=patterns),
        )
        if files:
            self.import_paths([Path(f) for f in files])

    def import_paths(self, paths: list[Path]) -> None:
        self.primary.setEnabled(False)
        self.status.setText(strings.VOICE_IMPORTING)
        run_async(
            lambda: self._ws.voices.import_files(paths),
            self._on_imported,
            self._on_import_failed,
        )

    def _on_imported(self, report: ImportReport) -> None:
        self.primary.setEnabled(True)
        parts = [strings.VOICE_IMPORT_DONE.format(imported=fa_digits(len(report.imported)))]
        if report.already_present:
            parts.append(strings.VOICE_IMPORT_DUP.format(n=fa_digits(len(report.already_present))))
        if report.unsupported:
            parts.append(
                strings.VOICE_IMPORT_UNSUPPORTED.format(n=fa_digits(len(report.unsupported)))
            )
        if report.failed:
            parts.append(strings.VOICE_IMPORT_FAILED.format(n=fa_digits(len(report.failed))))
        self.status.setText("، ".join(parts))
        QTimer.singleShot(8000, lambda: self.status.setText(""))
        self._events.data_changed.emit()
        first = report.imported[0].id if report.imported else None
        self.refresh(select_id=first)

    def _on_import_failed(self, exc: BaseException) -> None:
        self.primary.setEnabled(True)
        self.status.setText("")
        show_error(self, exc)

    def delete_item(self, item_id: int) -> None:
        voice = self._voice
        name = Path(voice.file_path).name if voice and voice.id == item_id else ""
        if not confirm(self, strings.VOICE_DELETE_CONFIRM.format(name=name)):
            return
        try:
            self._ws.voices.delete(item_id)
        except Exception as exc:
            show_error(self, exc)
        self._voice = None
        self._events.data_changed.emit()
        self.refresh()
        self.list.setFocus()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        files: list[Path] = []
        for path in paths:
            if path.is_dir():
                files += [p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS]
            else:
                files.append(path)
        if files:
            self.import_paths(files)
            event.acceptProposedAction()


class IdeasPage(ListPage):
    """A new idea exists only in the editor until its first non-empty autosave."""

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__(strings.IDEAS_TITLE, strings.IDEA_NEW, strings.IDEA_EMPTY)
        self._ws = workspace
        self._events = events
        self._idea: IdeaNote | None = None
        self._drafting = False

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        self.text = QPlainTextEdit(objectName="ideaText")
        self.text.setPlaceholderText(strings.IDEA_PLACEHOLDER)
        self.text.setTabChangesFocus(True)
        self.text.textChanged.connect(self._schedule_save)
        col.addWidget(self.text, 1)
        form = QFormLayout()
        self.tag_input = TagInput(workspace.tags, events, limit=MAX_TAGS_PER_ITEM)
        self.tag_input.tags_changed.connect(self._save_tags)
        form.addRow(strings.TAG_LABEL, self.tag_input)
        col.addLayout(form)
        bottom = QHBoxLayout()
        self.meta = QLabel(objectName="muted")
        bottom.addWidget(self.meta)
        bottom.addStretch(1)
        delete = _danger_button(strings.DELETE)
        delete.clicked.connect(self._delete_current)
        bottom.addWidget(delete)
        col.addLayout(bottom)

        self._timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_text)
        self._loading = False

    def _row(self, idea: IdeaNote) -> Row:
        assert idea.id is not None
        names = [t.name for t in self._ws.tags.by_ids(idea.tag_ids)]
        subtitle = format_datetime(idea.updated_at)
        if names:
            subtitle += "  ·  " + "، ".join(names)
        return Row(idea.id, _first_line(idea.text), subtitle)

    def rows(self) -> list[Row]:
        return [self._row(i) for i in self._ws.ideas.list_all()]

    def show_item(self, item_id: int) -> None:
        self.flush()
        try:
            idea = self._ws.ideas.get(item_id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._drafting = False
        self._idea = idea
        self._loading = True
        self.text.setPlainText(idea.text)
        self._loading = False
        self.tag_input.set_tag_ids(idea.tag_ids)
        self.meta.setText(strings.UPDATED_AT.format(when=format_datetime(idea.updated_at)))

    def clear_editor(self) -> None:
        self._idea = None

    def focus_editor(self) -> None:
        self.text.setFocus()

    def primary_action(self) -> None:
        self.flush()
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self._idea = None
        self._drafting = True
        self.detail.setCurrentIndex(1)
        self._loading = True
        self.text.clear()
        self._loading = False
        self.tag_input.set_tag_ids([])
        self.meta.setText(strings.IDEA_UNSAVED)
        self.text.setFocus()

    def _schedule_save(self) -> None:
        if not self._loading:
            self._timer.start()

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._save_text()

    def external_change(self) -> None:
        """Ideas arrived from outside (Bale bot). Never disturb a draft or pending autosave;
        the list reloads on the next show anyway."""
        if self.isVisible() and not self._drafting and not self._timer.isActive():
            self.refresh(load=False)

    def _save_text(self) -> None:
        text = self.text.toPlainText()
        if not text.strip():
            return  # never persist an empty idea; deleting is explicit
        try:
            if self._idea is None and self._drafting:
                idea = self._ws.ideas.create(text, self.tag_input.tag_ids())
                self._drafting = False
                self._idea = idea
                self._events.data_changed.emit()
                self.refresh(select_id=idea.id, load=False)  # keep the cursor where it is
            elif self._idea is not None and self._idea.id is not None:
                self._idea = self._ws.ideas.update_text(self._idea.id, text)
                self.update_row(self._row(self._idea))
                self._events.data_changed.emit()
            else:
                return
        except Exception as exc:
            show_error(self, exc)
            return
        self.meta.setText(strings.UPDATED_AT.format(when=format_datetime(self._idea.updated_at)))

    def _save_tags(self, tag_ids: list[int]) -> None:
        idea = self._idea
        if idea is None or idea.id is None:
            return  # draft: tags are passed on create
        try:
            self._idea = self._ws.ideas.set_tags(idea.id, tag_ids)
            self.update_row(self._row(self._idea))
            self._events.data_changed.emit()
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(idea.tag_ids)

    def delete_item(self, item_id: int) -> None:
        if not confirm(self, strings.IDEA_DELETE_CONFIRM):
            return
        self._timer.stop()
        try:
            self._ws.ideas.delete(item_id)
        except Exception as exc:
            show_error(self, exc)
        self._idea = None
        self._events.data_changed.emit()
        self.refresh()
        self.list.setFocus()

    def hideEvent(self, event: QHideEvent) -> None:
        self.flush()
        super().hideEvent(event)
