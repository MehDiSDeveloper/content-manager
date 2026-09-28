"""The Ideas page: audio ideas (voices) and text ideas in one list.

An idea is an idea whether it was spoken or written, so both live in one place and are
found by one search; the switch over the list narrows it to one kind when that is what
the user wants. Choosing a row shows the editor that fits it — the player with its notes
and transcript, or the text box — in the same pane.

The search above the list (`widgets/facet_search.py`) reads titles and tags, and the
content (idea text, voice transcripts) once its switch is on. A file name is an audio
idea's title and the first line a text idea's, as everywhere else in the app.

Ideas can be archived and put in the trash (`ShelfListPage`); a delete here is a move to
the trash, which is why it asks nothing — the toast offers the undo, and the trash page
the restore.

Several rows can be selected at once (Ctrl/Shift+click, Ctrl+A). The editor then gives
way to a pane of what can be done to all of them — transcribe, archive, move to the
trash, delete forever — and each of those is one step of the undo history, except
deleting forever, which is the one thing here that asks first and cannot be taken back.
"""

import subprocess
from collections.abc import Callable, Hashable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QHideEvent,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import IdeaNote, Shelved, Voice
from podcast_workspace.domain.lifecycle import TRASH_DAYS, ArchiveScope, TrashKind
from podcast_workspace.domain.list_filter import FacetFilter
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM
from podcast_workspace.domain.text import flatten_for_filter
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport
from podcast_workspace.services.history import ChangeKind
from podcast_workspace.services.transcription import whisper_installed
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.icons import text_icon, voices_icon
from podcast_workspace.ui.pages.base import ID_ROLE, ListPage, ListPageState, Row
from podcast_workspace.ui.pages.content_pages import (
    AUTOSAVE_DELAY_MS,
    PathLabel,
    danger_button,
    first_line,
    tag_labels,
    tag_map,
)
from podcast_workspace.ui.player.player_widget import PlayerWidget, install_player_keys
from podcast_workspace.ui.player.timestamp_panel import TimestampPanel
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs, TranscriptPanel
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    format_datetime,
    format_duration,
    local_digits,
    run_async,
    show_error,
)
from podcast_workspace.ui.theme import section_ink
from podcast_workspace.ui.widgets.facet_search import FacetSearchBar, FacetState
from podcast_workspace.ui.widgets.key_hint import attach_key_hint
from podcast_workspace.ui.widgets.scope_switch import ChoiceSwitch, ScopeSwitch
from podcast_workspace.ui.widgets.tag_input import TagInput


class IdeaKind(StrEnum):
    AUDIO = "audio"
    TEXT = "text"


KIND_ALL = "all"  # the kind switch's third position: both kinds


@dataclass(frozen=True)
class IdeaKey:
    """A row's id: voice and idea ids are counted separately, so the kind is part of it."""

    kind: IdeaKind
    item_id: int


def audio_key(voice_id: int) -> IdeaKey:
    return IdeaKey(IdeaKind.AUDIO, voice_id)


def text_key(idea_id: int) -> IdeaKey:
    return IdeaKey(IdeaKind.TEXT, idea_id)


class ShelfControls:
    """One editor pane's «Archive» and «Move to trash» buttons and its archived badge."""

    def __init__(self, on_toggle: Callable[[], None], on_trash: Callable[[], None]) -> None:
        self.archive_button = QPushButton(strings.ARCHIVE)
        self.archive_button.clicked.connect(on_toggle)
        self.trash_button = danger_button(strings.MOVE_TO_TRASH)
        self.trash_button.setToolTip(
            strings.MOVE_TO_TRASH_TOOLTIP.format(days=local_digits(TRASH_DAYS))
        )
        self.trash_button.clicked.connect(on_trash)
        self.badge = QLabel(strings.ARCHIVED_BADGE, objectName="countPill")
        self.badge.setToolTip(strings.ARCHIVED_NOTE)
        self.badge.hide()

    def add_buttons(self, row: QHBoxLayout) -> None:
        """At the end of the editor's action row."""
        row.addWidget(self.archive_button)
        row.addWidget(self.trash_button)

    def sync(self, item: Shelved | None) -> None:
        """Follow the item shown; a draft (None) is an active item that cannot be moved yet."""
        archived = item is not None and item.archived
        self.archive_button.setText(strings.UNARCHIVE if archived else strings.ARCHIVE)
        self.archive_button.setToolTip(
            strings.UNARCHIVE_TOOLTIP if archived else strings.ARCHIVE_TOOLTIP
        )
        self.badge.setVisible(archived)


class ShelfListPage(ListPage):
    """A list whose items can be archived and put in the trash.

    The switch over the list starts on «active» each time the app opens, so archived
    items stay out of the way until asked for. An item reached from elsewhere (search,
    a tag, an episode, an undo) that the switch would hide widens it to «all» instead:
    an item the user was sent to must be visible, the same promise the filter box keeps.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.scope = ArchiveScope.ACTIVE
        self.scope_switch = ScopeSwitch()
        self.scope_switch.scope_changed.connect(self._on_scope_changed)
        # Other switches join this row, ahead of the archive switch.
        self.switch_row = QHBoxLayout()
        self.switch_row.setSpacing(6)
        self.switch_row.addStretch(1)
        self.switch_row.addWidget(self.scope_switch)
        side = self.list_side.layout()
        assert isinstance(side, QVBoxLayout)
        side.insertLayout(2, self.switch_row)  # under the title and status, over the filter

    # to implement ----------------------------------------------------------------------
    def find_item(self, item_id: Hashable) -> Shelved | None:
        raise NotImplementedError

    def store_archived(self, item_id: Hashable, archived: bool) -> None:
        raise NotImplementedError

    def store_trashed(self, item_id: Hashable) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        """Write a pending autosave before the item leaves the list."""

    # the switch ------------------------------------------------------------------------
    def _on_scope_changed(self, scope: ArchiveScope) -> None:
        self.scope = scope
        self.refresh()

    def set_scope(self, scope: ArchiveScope) -> None:
        self.scope = scope
        self.scope_switch.set_scope(scope)

    def badge(self, item: Shelved, subtitle: str) -> str:
        """Across active and archived together, each archived row says so."""
        if item.archived and self.scope is ArchiveScope.ALL:
            return strings.ARCHIVED_BADGE + "  ·  " + subtitle
        return subtitle

    def select(self, item_id: Hashable) -> None:
        item = self.find_item(item_id)
        if item is not None and not item.in_trash and not self.scope.shows(item.archived):
            self.set_scope(ArchiveScope.ALL)
        super().select(item_id)

    # archive / trash -------------------------------------------------------------------
    def row_actions(self, item_id: Hashable) -> list[tuple[str, Callable[[], None]]]:
        item = self.find_item(item_id)
        if item is None:
            return []
        label = strings.UNARCHIVE if item.archived else strings.ARCHIVE
        return [
            (label, lambda: self.toggle_archived(item_id)),
            (strings.MOVE_TO_TRASH, lambda: self.delete_item(item_id)),
        ]

    def toggle_current(self) -> None:
        item_id = self.current_id()
        if item_id is not None:
            self.toggle_archived(item_id)

    def trash_current(self) -> None:
        self._delete_current()

    def toggle_archived(self, item_id: Hashable) -> None:
        item = self.find_item(item_id)
        if item is None:
            return
        self.flush()
        try:
            self.store_archived(item_id, not item.archived)
        except Exception as exc:
            show_error(self, exc)
            return
        self._events.data_changed.emit()  # type: ignore[attr-defined]
        self._refresh_near(item_id)

    def delete_item(self, item_id: Hashable) -> None:
        """Into the trash, without asking: it is one undo (or one restore) away."""
        self.flush()
        try:
            self.store_trashed(item_id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._events.data_changed.emit()  # type: ignore[attr-defined]
        self._refresh_near(item_id)
        self.list.setFocus()

    def _refresh_near(self, item_id: Hashable) -> None:
        """Reload; if the row left the list, land on the one that took its place rather
        than jumping back to the top."""
        row = next(
            (i for i in range(self.list.count()) if self.list.item(i).data(ID_ROLE) == item_id),
            0,
        )
        self.refresh()
        if self.current_id() != item_id and self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> ListPageState:
        state = super().nav_state()
        return replace(state, extra={**state.extra, "scope": self.scope.value})

    def restore_nav_state(self, state: object) -> None:
        if isinstance(state, ListPageState) and "scope" in state.extra:
            self.set_scope(ArchiveScope(str(state.extra["scope"])))
        super().restore_nav_state(state)


class VoicePane(QWidget):
    """An audio idea: its file, tags, the player, and its notes and transcript."""

    TAB_NOTES, TAB_TRANSCRIPT = 0, 1
    settings_requested = Signal()
    voice_changed = Signal(object)  # Voice whose row should be redrawn
    transcript_changed = Signal(int)  # voice id

    def __init__(
        self,
        workspace: Workspace,
        events: AppEvents,
        player: Player,
        jobs: TranscriptionJobs,
        shelf: ShelfControls,
    ) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self.shelf = shelf
        self.voice: Voice | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        self.name = QLabel(objectName="editorTitle")
        self.name.setWordWrap(True)
        col.addWidget(self.name)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)
        self.meta = QLabel(objectName="muted")
        meta_row.addWidget(self.meta)
        self.missing = QLabel(strings.VOICE_MISSING, objectName="warning")
        meta_row.addWidget(self.missing)
        meta_row.addWidget(shelf.badge)
        meta_row.addStretch(1)
        # The full path is reference information, not something to read every time:
        # one muted, elided line that copies itself on click.
        self.path = PathLabel()
        meta_row.addWidget(self.path, 2)
        col.addLayout(meta_row)

        tags_row = QHBoxLayout()
        tags_row.setSpacing(10)
        tag_label = QLabel(strings.TAG_LABEL, objectName="fieldLabel")
        tag_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        tags_row.addWidget(tag_label)
        self.tag_input = TagInput(workspace.tags, events, limit=MAX_TAGS_PER_ITEM)
        self.tag_input.tags_changed.connect(self._save_tags)
        tags_row.addWidget(self.tag_input, 1)
        col.addLayout(tags_row)

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
        self.transcript.changed.connect(self.transcript_changed)
        self.panels.addWidget(self.transcript)
        self.tabs.currentChanged.connect(self.panels.setCurrentIndex)
        col.addWidget(self.panels, 1)

        actions = QHBoxLayout()
        show = QPushButton(strings.VOICE_SHOW_IN_FOLDER)
        show.clicked.connect(self._show_in_folder)
        actions.addWidget(show)
        actions.addStretch(1)
        shelf.add_buttons(actions)
        col.addLayout(actions)

    def show_voice(self, voice: Voice) -> None:
        assert voice.id is not None
        self.voice = voice
        self.name.setText(Path(voice.file_path).name)
        self.path.set_path(voice.file_path)
        self.missing.setVisible(not Path(voice.file_path).exists())
        self.meta.setText(self._meta_text(voice))
        self.shelf.sync(voice)
        self.tag_input.set_tag_ids(voice.tag_ids)
        self.player.open_voice(voice.id, Path(voice.file_path), voice.duration_ms)
        self.notes.set_voice(voice.id)
        self.transcript.set_voice(voice.id)

    def clear(self) -> None:
        self.voice = None
        self.player.close_voice()
        self.notes.set_voice(None)
        self.transcript.set_voice(None)

    def focus_note(self, note_id: int) -> None:
        self.tabs.setCurrentIndex(self.TAB_NOTES)
        self.notes.focus_note(note_id)

    def show_transcript(self, query: str) -> None:
        self.tabs.setCurrentIndex(self.TAB_TRANSCRIPT)
        self.transcript.highlight_query(query)

    def toggle_tab(self) -> None:
        self.tabs.setCurrentIndex(1 - self.tabs.currentIndex())

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
        if self.voice is not None and self.voice.id == voice_id:
            self.voice = voice
            self.meta.setText(self._meta_text(voice))
        self.voice_changed.emit(voice)

    def _save_tags(self, tag_ids: list[int]) -> None:
        voice = self.voice
        if voice is None or voice.id is None:
            return
        try:
            self.voice = self._ws.voices.set_tags(voice.id, tag_ids)
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(voice.tag_ids)
            return
        self.voice_changed.emit(self.voice)
        self._events.data_changed.emit()

    def _show_in_folder(self) -> None:
        if self.voice is None:
            return
        path = Path(self.voice.file_path)
        if path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif path.parent.exists():
            subprocess.Popen(["explorer", str(path.parent)])


class TextPane(QWidget):
    """A text idea: the text (autosaved) and its tags. A new idea exists only here until
    its first non-empty autosave."""

    created = Signal(object)  # IdeaNote, from a draft's first save
    idea_changed = Signal(object)  # IdeaNote whose row should be redrawn

    def __init__(self, workspace: Workspace, events: AppEvents, shelf: ShelfControls) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self.shelf = shelf
        self.idea: IdeaNote | None = None
        self.drafting = False
        self._loading = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        self.text = QPlainTextEdit(objectName="ideaText")
        self.text.setPlaceholderText(strings.IDEA_PLACEHOLDER)
        self.text.setTabChangesFocus(True)
        self.text.textChanged.connect(self._schedule_save)
        col.addWidget(self.text, 1)
        tags_row = QHBoxLayout()
        tags_row.setSpacing(10)
        tag_label = QLabel(strings.TAG_LABEL, objectName="fieldLabel")
        tag_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        tags_row.addWidget(tag_label)
        self.tag_input = TagInput(workspace.tags, events, limit=MAX_TAGS_PER_ITEM)
        self.tag_input.tags_changed.connect(self._save_tags)
        tags_row.addWidget(self.tag_input, 1)
        col.addLayout(tags_row)
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.meta = QLabel(objectName="muted")
        bottom.addWidget(self.meta)
        bottom.addWidget(shelf.badge)
        bottom.addStretch(1)
        shelf.add_buttons(bottom)
        col.addLayout(bottom)

        self._timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_text)

    @property
    def busy(self) -> bool:
        """A draft or an unsaved edit: nothing from outside may reload under it."""
        return self.drafting or self._timer.isActive()

    def show_idea(self, idea: IdeaNote) -> None:
        self.flush()
        self.drafting = False
        self.idea = idea
        self._set_text(idea.text)
        self.tag_input.set_tag_ids(idea.tag_ids)
        self.meta.setText(strings.UPDATED_AT.format(when=format_datetime(idea.updated_at)))
        self.shelf.sync(idea)

    def begin_draft(self) -> None:
        self.flush()
        self.idea = None
        self.drafting = True
        self._set_text("")
        self.tag_input.set_tag_ids([])
        self.meta.setText(strings.IDEA_UNSAVED)
        self.shelf.sync(None)
        self.text.setFocus()

    def clear(self) -> None:
        self.flush()
        self.idea = None
        self.drafting = False

    def forget(self, idea_id: int) -> None:
        """The idea is leaving (trash): drop a pending save instead of writing it."""
        self._timer.stop()
        if self.idea is not None and self.idea.id == idea_id:
            self.idea = None

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._save_text()

    def _set_text(self, text: str) -> None:
        self._loading = True
        self.text.setPlainText(text)
        self._loading = False

    def _schedule_save(self) -> None:
        if not self._loading:
            self._timer.start()

    def _save_text(self) -> None:
        text = self.text.toPlainText()
        if not text.strip():
            return  # never persist an empty idea; deleting is explicit
        try:
            if self.idea is None and self.drafting:
                idea = self._ws.ideas.create(text, self.tag_input.tag_ids())
                self.drafting = False
                self.idea = idea
                self._events.data_changed.emit()
                self.created.emit(idea)
            elif self.idea is not None and self.idea.id is not None:
                self.idea = self._ws.ideas.update_text(self.idea.id, text)
                self.idea_changed.emit(self.idea)
                self._events.data_changed.emit()
            else:
                return
        except Exception as exc:
            show_error(self, exc)
            return
        self.meta.setText(strings.UPDATED_AT.format(when=format_datetime(self.idea.updated_at)))

    def _save_tags(self, tag_ids: list[int]) -> None:
        idea = self.idea
        if idea is None or idea.id is None:
            return  # draft: tags are passed on create
        try:
            self.idea = self._ws.ideas.set_tags(idea.id, tag_ids)
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(idea.tag_ids)
            return
        self.idea_changed.emit(self.idea)
        self._events.data_changed.emit()


class SelectionPane(QWidget):
    """What several selected rows can have done to them together. It takes the editor's
    place while more than one row is selected: one editor cannot show five items."""

    def __init__(self) -> None:
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        col.addStretch(1)
        self.count = QLabel(objectName="editorTitle")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.count)
        self.kinds = QLabel(objectName="muted")
        self.kinds.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.kinds)
        col.addSpacing(10)

        self.transcribe = QPushButton()
        self.archive = QPushButton()
        self.archive.setToolTip(strings.ARCHIVE_TOOLTIP)
        self.trash = danger_button("")
        self.trash.setToolTip(strings.MOVE_TO_TRASH_TOOLTIP.format(days=local_digits(TRASH_DAYS)))
        self.delete_forever = danger_button("")
        self.delete_forever.setToolTip(strings.DELETE_FOREVER_TOOLTIP)
        self.clear = QPushButton(strings.SEL_CLEAR, objectName="flatButton")
        self.clear.setToolTip("Esc")
        for button in (
            self.transcribe,
            self.archive,
            self.trash,
            self.delete_forever,
            self.clear,
        ):
            button.setMinimumWidth(260)
            col.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)

        col.addSpacing(10)
        hint = QLabel(strings.SEL_HINT, objectName="muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(hint)
        col.addStretch(2)

    def show_selection(self, audio: int, text: int, to_transcribe: int, all_archived: bool) -> None:
        n = local_digits(audio + text)
        self.count.setText(strings.SEL_COUNT.format(n=n))
        self.kinds.setText(
            strings.SEL_KINDS.format(audio=local_digits(audio), text=local_digits(text))
        )
        self.transcribe.setVisible(audio > 0)
        self.transcribe.setEnabled(to_transcribe > 0)
        self.transcribe.setText(strings.SEL_TRANSCRIBE.format(n=local_digits(to_transcribe)))
        self.transcribe.setToolTip("" if to_transcribe else strings.SEL_TRANSCRIBE_NONE)
        self.archive.setText(
            (strings.SEL_UNARCHIVE if all_archived else strings.SEL_ARCHIVE).format(n=n)
        )
        self.archive.setToolTip(
            strings.UNARCHIVE_TOOLTIP if all_archived else strings.ARCHIVE_TOOLTIP
        )
        self.trash.setText(strings.SEL_TRASH.format(n=n))
        self.delete_forever.setText(strings.SEL_DELETE_FOREVER.format(n=n))


class IdeasPage(ShelfListPage):
    settings_requested = Signal()

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
        super().__init__(
            strings.IDEAS_TITLE,
            strings.IDEA_NEW,
            strings.IDEA_EMPTY[KIND_ALL],
            list_weight=2,
            detail_weight=5,
        )
        self._ws = workspace
        self._events = events
        self._jobs = jobs
        self.kind = KIND_ALL
        self._facets = FacetFilter()
        self._transcribed: set[int] = set()
        self._note_counts: dict[int, int] = {}
        self._transcripts: dict[int, str] | None = None  # flattened; None: to be read
        events.data_changed.connect(self._forget_content)
        self.setAcceptDrops(True)
        self.primary.setToolTip(strings.IDEA_NEW_TOOLTIP)

        self.import_button = QPushButton(strings.VOICE_IMPORT)
        self.import_button.setToolTip(strings.VOICE_IMPORT_TOOLTIP)
        self.import_button.clicked.connect(self.import_dialog)
        self.header.insertWidget(self.header.indexOf(self.primary), self.import_button)
        for button in (self.import_button, self.primary):  # two buttons: neither may clip
            button.setMinimumWidth(button.sizeHint().width())

        self.kind_switch = ChoiceSwitch(
            (KIND_ALL, IdeaKind.AUDIO, IdeaKind.TEXT),
            {
                KIND_ALL: strings.IDEA_KINDS[KIND_ALL],
                IdeaKind.AUDIO: strings.IDEA_KINDS[IdeaKind.AUDIO],
                IdeaKind.TEXT: strings.IDEA_KINDS[IdeaKind.TEXT],
            },
            strings.IDEA_KIND_TOOLTIP,
        )
        self.kind_switch.choice_changed.connect(self._on_kind_changed)
        self.switch_row.insertWidget(0, self.kind_switch)

        side = self.list_side.layout()
        assert isinstance(side, QVBoxLayout)
        self.facets = FacetSearchBar(workspace.tags, events)
        self.facets.changed.connect(self._on_facets_changed)
        self.facets.leave_requested.connect(self.focus_main)
        # Ctrl+F finds here as on every page, Ctrl+I from anywhere: show the one that
        # always works.
        attach_key_hint(self.facets.edit, "Ctrl+I")
        side.insertWidget(side.indexOf(self.list), self.facets)
        # The count shares a line with «clear all», under the chips: the search's status.
        self.facets.footer.insertWidget(0, self.filter_count)

        self.transcribe_all = QPushButton(strings.TR_ALL, objectName="flatButton")
        self.transcribe_all.clicked.connect(self._transcribe_all)
        side.addWidget(self.transcribe_all, 0, Qt.AlignmentFlag.AlignLeading)
        jobs.queue_changed.connect(self._sync_transcribe_all)
        jobs.batch_ended.connect(self.status.setText)
        self._sync_transcribe_all()

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        self.panes = QStackedWidget()
        col.addWidget(self.panes)
        self.voice_pane = VoicePane(
            workspace, events, player, jobs, ShelfControls(self.toggle_current, self.trash_current)
        )
        self.voice_pane.settings_requested.connect(self.settings_requested)
        self.voice_pane.voice_changed.connect(lambda v: self.update_row(self._voice_row(v)))
        self.voice_pane.transcript_changed.connect(self._on_transcript_changed)
        self.panes.addWidget(self.voice_pane)
        self.text_pane = TextPane(
            workspace, events, ShelfControls(self.toggle_current, self.trash_current)
        )
        self.text_pane.created.connect(self._on_idea_created)
        self.text_pane.idea_changed.connect(lambda i: self.update_row(self._idea_row(i)))
        self.panes.addWidget(self.text_pane)

        # Several rows at once: Ctrl/Shift+click, Ctrl+A. The pane takes the editor's place.
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.selection_pane = SelectionPane()
        self.selection_pane.transcribe.clicked.connect(self.transcribe_selected)
        self.selection_pane.archive.clicked.connect(self.archive_selected)
        self.selection_pane.trash.clicked.connect(self.trash_selected)
        self.selection_pane.delete_forever.clicked.connect(self.delete_selected_forever)
        self.selection_pane.clear.clicked.connect(self._collapse_selection)
        self.detail.addWidget(self.selection_pane)
        # Qt reports the selection before the current row; settle once both have moved.
        self._selection_timer = QTimer(self, singleShot=True, interval=0)
        self._selection_timer.timeout.connect(self._sync_selection)
        self.list.itemSelectionChanged.connect(self._selection_timer.start)

        QShortcut(QKeySequence.StandardKey.Open, self, activated=self.import_dialog)
        QShortcut(
            QKeySequence("Ctrl+Tab"),
            self,
            activated=lambda: self._audio_shown() and self.voice_pane.toggle_tab(),
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        notes = self.voice_pane.notes
        install_player_keys(
            self,
            self.voice_pane.player.player,
            (("Insert", notes.begin_note), ("Ctrl+Return", notes.begin_note)),
            enabled=self._audio_shown,
        )

    # rows ------------------------------------------------------------------------------
    def rows(self) -> list[Row]:
        wanted = self.kind
        voices = self._ws.voices.list_all() if wanted != IdeaKind.TEXT else []
        ideas = self._ws.ideas.list_all() if wanted != IdeaKind.AUDIO else []
        if not voices and not ideas:
            self._empty_text = strings.IDEA_EMPTY[wanted]
        elif self.scope is ArchiveScope.ARCHIVED:
            self._empty_text = strings.IDEA_ARCHIVED_EMPTY[wanted]
        else:
            self._empty_text = strings.IDEA_ACTIVE_EMPTY[wanted]
        tags = tag_map(self._ws)
        if voices:
            self._transcribed = self._ws.transcripts.voice_ids()
            self._note_counts = self._ws.timestamp_notes.counts_by_voice()
        dated: list[tuple[datetime, Row]] = [
            (v.imported_at, self._voice_row(v, tags))
            for v in voices
            if self.scope.shows(v.archived)
        ]
        dated += [
            (i.updated_at, self._idea_row(i, tags)) for i in ideas if self.scope.shows(i.archived)
        ]
        dated.sort(key=lambda pair: pair[0], reverse=True)  # newest first, either kind
        return [row for _, row in dated]

    def _voice_row(self, voice: Voice, tags: dict[int, str] | None = None) -> Row:
        assert voice.id is not None
        names = tag_labels(self._ws, voice.tag_ids, tags)
        parts = [format_duration(voice.duration_ms), voice.format.upper()]
        # Tags go in ahead of the counts and the date: the subtitle is elided at the
        # list's width, and what a voice is about survives elision better than when it
        # arrived. The full line is in the row's tooltip either way.
        if names:
            parts.append(strings.LIST_SEPARATOR.join(names))
        notes = self._note_counts.get(voice.id, 0)
        if notes:
            parts.append(strings.VOICE_NOTE_COUNT.format(n=local_digits(notes)))
        if voice.id in self._transcribed:
            parts.append(strings.VOICE_HAS_TRANSCRIPT)
        parts.append(format_datetime(voice.imported_at))
        return Row(
            audio_key(voice.id),
            Path(voice.file_path).name,
            self.badge(voice, "  ·  ".join(p for p in parts if p)),
            names,
            frozenset(voice.tag_ids),
            self._transcript_text(voice.id),
            IdeaKind.AUDIO,
            voices_icon(section_ink("voices")),
        )

    def _idea_row(self, idea: IdeaNote, tags: dict[int, str] | None = None) -> Row:
        assert idea.id is not None
        names = tag_labels(self._ws, idea.tag_ids, tags)
        subtitle = format_datetime(idea.updated_at)
        if names:
            subtitle += "  ·  " + strings.LIST_SEPARATOR.join(names)
        return Row(
            text_key(idea.id),
            first_line(idea.text),
            self.badge(idea, subtitle),
            names,
            frozenset(idea.tag_ids),
            flatten_for_filter(idea.text) if self._facets.in_content else "",
            IdeaKind.TEXT,
            text_icon(section_ink("ideas")),
        )

    def _transcript_text(self, voice_id: int) -> str:
        """Read, and flattened, once per change to the data — and only while the search
        is asked to look in the content."""
        if not self._facets.in_content:
            return ""
        if self._transcripts is None:
            self._transcripts = {
                vid: flatten_for_filter(text) for vid, text in self._ws.transcripts.texts().items()
            }
        return self._transcripts.get(voice_id, "")

    def _forget_content(self) -> None:
        self._transcripts = None

    # the search ------------------------------------------------------------------------
    def row_matches(self, row: Row) -> bool:
        return self._facets.matches(row.title, row.tags, row.tag_ids, row.content)

    def filter_active(self) -> bool:
        return not self._facets.is_empty

    def _on_facets_changed(self) -> None:
        self._facets = self.facets.facet_filter()
        self.refresh()

    def _update_filter_count(self, shown_rows: list[Row], rows: list[Row]) -> None:
        super()._update_filter_count(shown_rows, rows)
        if not self.filter_active():
            return
        if self.kind == KIND_ALL:  # the answer to "how many of each?"
            audio = sum(1 for r in shown_rows if r.kind == IdeaKind.AUDIO)
            self.filter_count.setText(
                strings.FACET_COUNT_KINDS.format(
                    audio=local_digits(audio), text=local_digits(len(shown_rows) - audio)
                )
            )
        if rows and not shown_rows:
            self._empty_label.setText(
                strings.FACET_NO_MATCH
                if self._facets.in_content
                else strings.FACET_NO_MATCH_CONTENT
            )

    def clear_filter(self, reload: bool = True) -> None:
        if not self.facets.has_conditions():
            return
        self.facets.restore(FacetState(in_content=self.facets.in_content()))
        self._facets = self.facets.facet_filter()
        if reload:
            self.refresh()

    def focus_filter(self) -> None:
        self.facets.focus()

    # the kind switch -------------------------------------------------------------------
    def _on_kind_changed(self, kind: str) -> None:
        self.kind = kind
        self.transcribe_all.setVisible(kind != IdeaKind.TEXT)
        self.refresh()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.kind_switch.set_choice(kind)
        self.transcribe_all.setVisible(kind != IdeaKind.TEXT)

    def _show_kind(self, kind: IdeaKind) -> None:
        """Widen the switch when it would hide an idea of this kind."""
        if self.kind not in (KIND_ALL, kind):
            self.set_kind(KIND_ALL)

    # items -----------------------------------------------------------------------------
    def find_item(self, item_id: Hashable) -> Voice | IdeaNote | None:
        assert isinstance(item_id, IdeaKey)
        try:
            if item_id.kind is IdeaKind.AUDIO:
                return self._ws.voices.get(item_id.item_id)
            return self._ws.ideas.get(item_id.item_id)
        except Exception:
            return None

    def store_archived(self, item_id: Hashable, archived: bool) -> None:
        assert isinstance(item_id, IdeaKey)
        if item_id.kind is IdeaKind.AUDIO:
            self._ws.voices.set_archived(item_id.item_id, archived)
        else:
            self._ws.ideas.set_archived(item_id.item_id, archived)

    def store_trashed(self, item_id: Hashable) -> None:
        assert isinstance(item_id, IdeaKey)
        if item_id.kind is IdeaKind.AUDIO:
            self._ws.voices.delete(item_id.item_id)
        else:
            self.text_pane.forget(item_id.item_id)
            self._ws.ideas.delete(item_id.item_id)

    def show_item(self, item_id: Hashable) -> None:
        assert isinstance(item_id, IdeaKey)
        try:
            item: Voice | IdeaNote = (
                self._ws.voices.get(item_id.item_id)
                if item_id.kind is IdeaKind.AUDIO
                else self._ws.ideas.get(item_id.item_id)
            )
        except Exception as exc:
            show_error(self, exc)
            return
        if isinstance(item, Voice):
            self.text_pane.clear()
            self.panes.setCurrentWidget(self.voice_pane)
            self.voice_pane.show_voice(item)
        else:
            self.voice_pane.clear()  # nothing plays from a pane that is not on screen
            self.panes.setCurrentWidget(self.text_pane)
            self.text_pane.show_idea(item)

    def clear_editor(self) -> None:
        self.voice_pane.clear()
        self.text_pane.clear()

    def _audio_shown(self) -> bool:
        return self.panes.currentWidget() is self.voice_pane and self.voice_pane.voice is not None

    def focus_editor(self) -> None:
        if self.panes.currentWidget() is self.voice_pane:
            self.voice_pane.player.waveform.setFocus()
        else:
            self.text_pane.text.setFocus()

    def flush(self) -> None:
        self.text_pane.flush()

    def select(self, item_id: Hashable) -> None:
        assert isinstance(item_id, IdeaKey)
        self._show_kind(item_id.kind)
        super().select(item_id)

    # reached from elsewhere --------------------------------------------------------------
    def open_voice(self, voice_id: int) -> None:
        self.select(audio_key(voice_id))

    def open_idea(self, idea_id: int) -> None:
        self.select(text_key(idea_id))

    def open_note(self, voice_id: int, note_id: int) -> None:
        """Search hit on a timestamp note: open its voice with that note focused."""
        self.open_voice(voice_id)
        if self.voice_pane.voice is not None and self.voice_pane.voice.id == voice_id:
            self.voice_pane.focus_note(note_id)

    def open_transcript(self, voice_id: int, query: str) -> None:
        """Search hit on a transcript: open the voice on its transcript tab."""
        self.open_voice(voice_id)
        if self.voice_pane.voice is not None and self.voice_pane.voice.id == voice_id:
            self.voice_pane.show_transcript(query)

    def external_change(self) -> None:
        """Ideas arrived from outside (Bale bot). Never disturb a draft or pending autosave;
        the list reloads on the next show anyway."""
        if self.isVisible() and not self.text_pane.busy:
            self.refresh(load=False)

    # making ideas ----------------------------------------------------------------------
    def primary_action(self) -> None:
        """A new text idea."""
        self.flush()
        if self.scope is ArchiveScope.ARCHIVED:  # a new idea is an active one
            self.set_scope(ArchiveScope.ACTIVE)
        self._show_kind(IdeaKind.TEXT)
        self.clear_filter()  # an empty draft matches no filter; show it anyway
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.voice_pane.clear()
        self.detail.setCurrentIndex(1)
        self.panes.setCurrentWidget(self.text_pane)
        self.text_pane.begin_draft()

    def _on_idea_created(self, idea: IdeaNote) -> None:
        self.refresh(select_id=text_key(idea.id or 0), load=False)  # keep the cursor put

    def import_dialog(self) -> None:
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
        self.clear_filter(reload=False)  # imported files must not land behind a filter box
        if self.scope is ArchiveScope.ARCHIVED:  # ...nor behind the archive switch
            self.set_scope(ArchiveScope.ACTIVE)
        self._show_kind(IdeaKind.AUDIO)  # ...nor the kind switch
        self.import_button.setEnabled(False)
        self.status.setText(strings.VOICE_IMPORTING)
        run_async(
            lambda: self._ws.voices.import_files(paths),
            self._on_imported,
            self._on_import_failed,
        )

    def _on_imported(self, report: ImportReport) -> None:
        self.import_button.setEnabled(True)
        parts = [strings.VOICE_IMPORT_DONE.format(imported=local_digits(len(report.imported)))]
        if report.already_present:
            parts.append(
                strings.VOICE_IMPORT_DUP.format(n=local_digits(len(report.already_present)))
            )
        if report.unsupported:
            parts.append(
                strings.VOICE_IMPORT_UNSUPPORTED.format(n=local_digits(len(report.unsupported)))
            )
        if report.failed:
            parts.append(strings.VOICE_IMPORT_FAILED.format(n=local_digits(len(report.failed))))
        self.status.setText(strings.LIST_SEPARATOR.join(parts))
        QTimer.singleShot(8000, lambda: self.status.setText(""))
        self._events.data_changed.emit()
        first = report.imported[0].id if report.imported else None
        self.refresh(select_id=None if first is None else audio_key(first))

    def _on_import_failed(self, exc: BaseException) -> None:
        self.import_button.setEnabled(True)
        self.status.setText("")
        show_error(self, exc)

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

    # transcripts -----------------------------------------------------------------------
    def _sync_transcribe_all(self) -> None:
        batching = self._jobs.batching
        self.transcribe_all.setText(strings.TR_ALL_STOP if batching else strings.TR_ALL)
        self.transcribe_all.setToolTip("" if batching else strings.TR_ALL_TOOLTIP)

    def _transcribe_all(self) -> None:
        """Queue every voice the switch shows that has no transcript and whose file is there."""
        if self._jobs.batching:
            self._jobs.stop()
            return
        if not whisper_installed():
            self.status.setText(strings.TR_NOT_INSTALLED)
            return
        if self._ws.transcripts.model_path() is None:
            self.status.setText(strings.TR_MODEL_MISSING)
            return
        done = self._ws.transcripts.voice_ids()
        todo = [
            v.id
            for v in self._ws.voices.list_all(self.scope)
            if v.id is not None
            and v.id not in done
            and v.id != self._jobs.running
            and Path(v.file_path).is_file()
        ]
        if not todo:
            self.status.setText(strings.TR_ALL_NONE)
            return
        if confirm(
            self, strings.TR_ALL_CONFIRM.format(n=local_digits(len(todo))), strings.TR_ALL_START
        ):
            self.status.setText("")
            self._jobs.enqueue(todo)

    def _on_transcript_changed(self, voice_id: int) -> None:
        self._transcribed.add(voice_id)
        self._transcripts = None
        try:
            self.update_row(self._voice_row(self._ws.voices.get(voice_id)))
        except Exception:
            return  # removed meanwhile

    # several rows at once ----------------------------------------------------------------
    def selected_keys(self) -> list[IdeaKey]:
        """In list order; the current row when nothing is selected."""
        items = sorted(self.list.selectedItems(), key=self.list.row)
        if not items and self.list.currentItem() is not None:
            items = [self.list.currentItem()]
        return [item.data(ID_ROLE) for item in items]

    def _multi(self) -> bool:
        return len(self.list.selectedItems()) > 1

    def _on_current_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if self._multi():
            self._show_selection()
        else:
            super()._on_current_changed(current, previous)

    def _sync_selection(self) -> None:
        if self._multi():
            self._show_selection()
        elif self.detail.currentWidget() is self.selection_pane:
            super()._on_current_changed(self.list.currentItem(), None)

    def _show_selection(self) -> None:
        keys = self.selected_keys()
        voice_ids = {k.item_id for k in keys if k.kind is IdeaKind.AUDIO}
        idea_ids = {k.item_id for k in keys if k.kind is IdeaKind.TEXT}
        archived = [v.archived for v in self._ws.voices.list_all() if v.id in voice_ids]
        archived += [i.archived for i in self._ws.ideas.list_all() if i.id in idea_ids]
        if self.detail.currentWidget() is not self.selection_pane:
            self.flush()
            self.clear_editor()  # nothing plays from a pane that is not on screen
            self.detail.setCurrentWidget(self.selection_pane)
        self.selection_pane.show_selection(
            len(voice_ids),
            len(idea_ids),
            len(self._to_transcribe(voice_ids)[0]),
            bool(archived) and all(archived),
        )

    def _collapse_selection(self) -> None:
        """Back to the one current row (Esc)."""
        current = self.list.currentItem()
        if current is not None:
            # The plain call only replaces Qt's uncommitted selection: rows picked with
            # Ctrl+click would stay selected.
            self.list.setCurrentItem(current, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.list.setFocus()

    def refresh(self, select_id: Hashable | None = None, load: bool = True) -> None:
        super().refresh(select_id, load)
        self._selection_timer.start()  # a reload drops the selection without a signal

    def _first_selected_row(self) -> int:
        rows = [self.list.row(item) for item in self.list.selectedItems()]
        return min(rows) if rows else max(self.list.currentRow(), 0)

    def _land(self, row: int) -> None:
        """Reload after rows left, on the row that took the place of the first of them."""
        self.refresh()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))
        self.list.setFocus()

    def _each_selected(self, kind: ChangeKind, act: Callable[[IdeaKey], None]) -> None:
        """Do `act` to every selected row, as one step of the undo history."""
        keys = self.selected_keys()
        if not keys:
            return
        self.flush()
        row = self._first_selected_row()
        try:
            with self._ws.history.grouped(kind):
                for key in keys:
                    act(key)
        except Exception as exc:
            show_error(self, exc)
        self._events.data_changed.emit()
        self._land(row)

    def archive_selected(self) -> None:
        """Archive them all, or — when every one already is — bring them all back."""
        keys = self.selected_keys()
        items = [self.find_item(k) for k in keys]
        archive = not all(item is not None and item.archived for item in items)
        self._each_selected(
            ChangeKind.ARCHIVE if archive else ChangeKind.UNARCHIVE,
            lambda key: self.store_archived(key, archive),
        )

    def trash_selected(self) -> None:
        keys = self.selected_keys()
        if len(keys) == 1:
            self.delete_item(keys[0])
        else:
            self._each_selected(ChangeKind.TRASH, self.store_trashed)

    def delete_selected_forever(self) -> None:
        keys = self.selected_keys()
        if not keys or not confirm(
            self,
            strings.DELETE_FOREVER_CONFIRM.format(n=local_digits(len(keys))),
            strings.DELETE_FOREVER,
        ):
            return
        row = self._first_selected_row()
        voice_ids = [k.item_id for k in keys if k.kind is IdeaKind.AUDIO]
        for key in keys:
            if key.kind is IdeaKind.TEXT:
                self.text_pane.forget(key.item_id)  # no autosave may bring it back
        self._jobs.drop(voice_ids)
        self.clear_editor()
        try:
            report = self._ws.trash.delete_forever(
                (TrashKind.VOICE if k.kind is IdeaKind.AUDIO else TrashKind.IDEA, k.item_id)
                for k in keys
            )
        except Exception as exc:
            show_error(self, exc)
            report = None
        self._events.data_changed.emit()
        self._land(row)
        if report is not None:
            self.status.setText(strings.DELETE_FOREVER_DONE.format(n=local_digits(len(report))))
            QTimer.singleShot(6000, lambda: self.status.setText(""))

    def _to_transcribe(self, voice_ids: set[int]) -> tuple[list[int], int]:
        """Of these voices, the ones a transcription can start on, and how many are
        skipped for already having a transcript."""
        done = self._ws.transcripts.voice_ids()
        todo = [
            v.id
            for v in self._ws.voices.list_all()
            if v.id in voice_ids
            and v.id not in done
            and v.id != self._jobs.running
            and not self._jobs.is_queued(v.id)
            and Path(v.file_path).is_file()
        ]
        return todo, len(voice_ids & done)

    def transcribe_selected(self) -> None:
        if not whisper_installed():
            self.status.setText(strings.TR_NOT_INSTALLED)
            return
        if self._ws.transcripts.model_path() is None:
            self.status.setText(strings.TR_MODEL_MISSING)
            return
        voice_ids = {k.item_id for k in self.selected_keys() if k.kind is IdeaKind.AUDIO}
        todo, skipped = self._to_transcribe(voice_ids)
        if not todo:
            self.status.setText(strings.SEL_TRANSCRIBE_NONE)
            return
        text = strings.SEL_TRANSCRIBE_CONFIRM.format(n=local_digits(len(todo)))
        if skipped:
            text += "\n" + strings.SEL_TRANSCRIBE_SKIPPED.format(n=local_digits(skipped))
        if confirm(self, text, strings.TR_ALL_START):
            added = self._jobs.enqueue(todo)
            self.status.setText(strings.SEL_QUEUED.format(n=local_digits(added)))
            self._show_selection()

    def row_actions(self, item_id: Hashable) -> list[tuple[str, Callable[[], None]]]:
        actions = super().row_actions(item_id)
        return [*actions, (strings.DELETE_FOREVER_MENU, self.delete_selected_forever)]

    def _row_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None or not (item.isSelected() and self._multi()):
            super()._row_menu(pos)  # one row: it becomes the selection
            return
        pane = self.selection_pane
        menu = QMenu(self.list)
        for button, callback in (
            (pane.transcribe, self.transcribe_selected),
            (pane.archive, self.archive_selected),
            (pane.trash, self.trash_selected),
            (pane.delete_forever, self.delete_selected_forever),
        ):
            if button.isVisible() and button.isEnabled():
                menu.addAction(button.text(), callback)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.list and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            if key == Qt.Key.Key_Delete:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.delete_selected_forever()
                else:
                    self.trash_selected()
                return True
            if self._multi() and key == Qt.Key.Key_Escape:
                self._collapse_selection()
                return True
            if self._multi() and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True  # no single editor to walk into
        return super().eventFilter(watched, event)

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> ListPageState:
        state = super().nav_state()
        extra = {**state.extra, "kind": self.kind, "facets": self.facets.state()}
        return replace(state, extra=extra)

    def restore_nav_state(self, state: object) -> None:
        if isinstance(state, ListPageState):
            kind = state.extra.get("kind")
            if isinstance(kind, str):
                self.set_kind(kind)
            facets = state.extra.get("facets")
            if isinstance(facets, FacetState):
                self.facets.restore(facets)
                self._facets = self.facets.facet_filter()
        super().restore_nav_state(state)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and self.isVisible():
            self.refresh(load=False)  # the row icons are painted in the theme's inks

    def hideEvent(self, event: QHideEvent) -> None:
        self.flush()
        super().hideEvent(event)
