"""Episode workspace: one view for an episode's notes, linked material, status and next action,
plus the smart-link side panel (Voices and IdeaNotes sharing its tags).

It is the detail pane of the Episodes page, not a page of its own: choosing an episode in
the list shows it here, in place, and the list stays beside it. There is one way to see
an episode and the frame never changes under the user; wanting more room to write is
answered by hiding the list (the header's first button, Ctrl+L), which the user does and
undoes on purpose, rather than by a mode the app switches into on a double-click.

Layout (RTL): header row, next action + tags, then [main column | materials panel].
Main column: note tabs + editor.

Opening something in the materials panel shows it there (`material_preview.py`): the
panel widens and turns into the item — a text idea to read, an audio idea to play with
its transcript — and turns back into the list with its arrow or Esc. Writing with the
material beside the note is the job; going to the Ideas page to look at it, and Back
again, broke the thread every time. «Open in Ideas» is still there for editing it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Episode, EpisodeNote, EpisodeStatus
from podcast_workspace.domain.errors import NotFoundError
from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.domain.pipeline import days_untouched, is_stale
from podcast_workspace.domain.smart_links import LinkKind, SmartLink
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.icons import NAV_ICON_SIZE
from podcast_workspace.ui.pages.base import SUBTITLE_ROLE, TwoLineDelegate
from podcast_workspace.ui.pages.material_preview import MaterialPreview
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs
from podcast_workspace.ui.seasons import create_season
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    format_datetime,
    format_duration,
    local_digits,
    log_swallowed,
    numbered,
    show_error,
)
from podcast_workspace.ui.widgets.key_hint import add_key_hint
from podcast_workspace.ui.widgets.number_box import NumberBox
from podcast_workspace.ui.widgets.picker import PickerDialog
from podcast_workspace.ui.widgets.publish_checklist import PublishChecklistButton
from podcast_workspace.ui.widgets.script_prompt import ScriptPromptDialog
from podcast_workspace.ui.widgets.tag_input import TagInput

AUTOSAVE_DELAY_MS = 700
SUMMARY_LINES = 3
NEW_SEASON = "new"  # the season box's last entry: make one and file the episode there
SIDE_PANEL_MIN_WIDTH = 280
SIDE_PANEL_MAX_WIDTH = 380
# Previewing, the panel takes as much room as the note, within these bounds.
PREVIEW_MIN_WIDTH = 430
PREVIEW_MAX_WIDTH = 640
ID_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole + 2


def _first_line(text: str, width: int = 60) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


def note_label(note: EpisodeNote) -> str:
    return note.title or _first_line(note.body, 28) or strings.UNTITLED_NOTE


def stale_text(episode: Episode, now: datetime | None = None) -> str:
    """Badge text, or "" when the episode is not stale."""
    now = now or datetime.now(UTC)
    if not is_stale(episode, now):
        return ""
    return strings.STALE_BADGE.format(days=local_digits(days_untouched(episode, now)))


class _LinkedList(QListWidget):
    """Linked voices or ideas. Double-click/Enter opens, Delete unlinks. A single click only
    selects: it must not carry the user off the episode."""

    open_item = Signal(int)
    unlink_item = Signal(int)

    def __init__(self) -> None:
        super().__init__(objectName="linkedList")
        self.setItemDelegate(TwoLineDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemDoubleClicked.connect(lambda item: self.open_item.emit(int(item.data(ID_ROLE))))

    def current_id(self) -> int | None:
        item = self.currentItem()
        return None if item is None else int(item.data(ID_ROLE))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        item_id = self.current_id()
        if item_id is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_item.emit(item_id)
        elif item_id is not None and event.key() == Qt.Key.Key_Delete:
            self.unlink_item.emit(item_id)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event: QEvent) -> None:  # type: ignore[override]
        item = self.itemAt(event.pos())  # type: ignore[attr-defined]
        if item is None:
            return
        item_id = int(item.data(ID_ROLE))
        menu = QMenu(self)
        menu.addAction(strings.WS_OPEN, lambda: self.open_item.emit(item_id))
        menu.addAction(strings.WS_UNLINK, lambda: self.unlink_item.emit(item_id))
        menu.exec(event.globalPos())  # type: ignore[attr-defined]


class MaterialsPanel(QFrame):
    """Everything attached to (or suggested for) the episode, in one place.

    Three tabs — linked voices, linked ideas, same-tag suggestions — instead of two
    boxes under the editor plus a separate suggestion rail: the note editor keeps the
    whole main column, and one list at a time is enough to look at.

    Opening an item (double-click, Enter, «Open») turns the panel into its preview; the
    lists wait behind it, as they were.
    """

    TAB_VOICES, TAB_IDEAS, TAB_SMART = 0, 1, 2

    open_item = Signal(object, int)  # LinkKind, item_id
    toggle_link = Signal(object, int, bool)  # LinkKind, item_id, link?
    add_requested = Signal(object)  # LinkKind
    record_requested = Signal()

    def __init__(self, preview: MaterialPreview) -> None:
        super().__init__(objectName="sidePanel")
        self.setMinimumWidth(SIDE_PANEL_MIN_WIDTH)
        self.setMaximumWidth(SIDE_PANEL_MAX_WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        browse = QWidget()
        col = QVBoxLayout(browse)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self.pages.addWidget(browse)
        self.preview = preview
        self.pages.addWidget(preview)
        col.addWidget(QLabel(strings.WS_MATERIALS, objectName="panelTitle"))

        self.tabs = QTabBar(objectName="panelTabs")
        self.tabs.setExpanding(True)
        # Three short labels share a narrow panel: shrink them, never scroll them.
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setDocumentMode(True)
        for label in (strings.WS_TAB_VOICES, strings.WS_TAB_IDEAS, strings.WS_TAB_SMART):
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        col.addWidget(self.tabs)

        self.voices_list = _LinkedList()
        self.voices_list.open_item.connect(lambda i: self.open_item.emit(LinkKind.VOICE, i))
        self.voices_list.unlink_item.connect(
            lambda i: self.toggle_link.emit(LinkKind.VOICE, i, False)
        )
        self.ideas_list = _LinkedList()
        self.ideas_list.open_item.connect(lambda i: self.open_item.emit(LinkKind.IDEA, i))
        self.ideas_list.unlink_item.connect(
            lambda i: self.toggle_link.emit(LinkKind.IDEA, i, False)
        )
        self.smart_list = QListWidget(objectName="smartList")
        self.smart_list.setItemDelegate(TwoLineDelegate(self.smart_list))
        self.smart_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Opening is what a double-click does in every list here; linking has its own
        # button (and Space), so no double-click can quietly unlink something.
        self.smart_list.itemDoubleClicked.connect(lambda _i: self._open_current())
        self.smart_list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self.smart_list.installEventFilter(self)

        self.stack = QStackedWidget()
        for widget in (self.voices_list, self.ideas_list, self.smart_list):
            self.stack.addWidget(widget)
        col.addWidget(self.stack, 1)

        self.hint = QLabel(objectName="muted")
        self.hint.setWordWrap(True)
        self.hint.linkActivated.connect(lambda _href: self.show_tab(self.TAB_SMART))
        col.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.primary_button = QPushButton()
        self.primary_button.clicked.connect(self._primary)
        buttons.addWidget(self.primary_button, 1)
        self.open_button = QPushButton(strings.WS_OPEN.split(" (")[0])
        self.open_button.setToolTip(strings.WS_OPEN_TOOLTIP)
        self.open_button.clicked.connect(self._open_current)
        buttons.addWidget(self.open_button)
        col.addLayout(buttons)

        self._linked: dict[tuple[LinkKind, int], bool] = {}
        self._counts = [0, 0, 0]
        self._more = [0, 0]  # unlinked suggestions of each kind, for the linked tabs' hint
        self._has_tags = False
        self._sync_buttons()

    # filling ---------------------------------------------------------------------------
    def show_linked(self, kind: LinkKind, rows: list[tuple[int, str, str]]) -> None:
        widget = self.voices_list if kind is LinkKind.VOICE else self.ideas_list
        keep = widget.current_id()
        widget.clear()
        for item_id, title, subtitle in rows:
            item = QListWidgetItem(title)
            item.setData(ID_ROLE, item_id)
            item.setData(SUBTITLE_ROLE, subtitle)
            item.setToolTip(title)
            widget.addItem(item)
            if item_id == keep:
                widget.setCurrentItem(item)
        index = self.TAB_VOICES if kind is LinkKind.VOICE else self.TAB_IDEAS
        self._counts[index] = len(rows)
        self._update_tab_labels()
        self._sync_buttons()

    def show_links(
        self,
        links: list[SmartLink],
        names: dict[tuple[LinkKind, int], str],
        tag_names: dict[int, str],
        linked: set[tuple[LinkKind, int]],
        has_tags: bool,
    ) -> None:
        current = self._current_smart_key()
        self.smart_list.clear()
        self._linked = {}
        self._has_tags = has_tags
        target = None
        for link in links:
            key = (link.kind, link.item_id)
            shared = strings.LIST_SEPARATOR.join(
                sorted(tag_names.get(t, "?") for t in link.shared_tag_ids)
            )
            kind = strings.KIND_VOICE if link.kind is LinkKind.VOICE else strings.KIND_IDEA
            subtitle = strings.WS_SMART_SUBTITLE.format(
                kind=kind, n=local_digits(link.score), names=shared
            )
            is_linked = key in linked
            if is_linked:
                subtitle = strings.WS_SMART_LINKED + strings.LIST_SEPARATOR + subtitle
            item = QListWidgetItem(names.get(key, "?"))
            item.setData(ID_ROLE, link.item_id)
            item.setData(KIND_ROLE, link.kind)
            item.setData(SUBTITLE_ROLE, subtitle)
            item.setToolTip(subtitle)
            self.smart_list.addItem(item)
            self._linked[key] = is_linked
            if key == current:
                target = item
        if target is not None:
            self.smart_list.setCurrentItem(target)
        elif self.smart_list.count():
            self.smart_list.setCurrentRow(0)
        self._more = [
            sum(1 for link in links if link.kind is kind and not self._linked[(kind, link.item_id)])
            for kind in (LinkKind.VOICE, LinkKind.IDEA)
        ]
        self._counts[self.TAB_SMART] = len(links)
        self._update_tab_labels()
        self._sync_buttons()

    def _update_tab_labels(self) -> None:
        for index, label in enumerate(
            (strings.WS_TAB_VOICES, strings.WS_TAB_IDEAS, strings.WS_TAB_SMART)
        ):
            count = self._counts[index]
            self.tabs.setTabText(
                index,
                strings.WS_TAB_COUNT.format(label=label, n=local_digits(count)) if count else label,
            )

    # behaviour -------------------------------------------------------------------------
    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._sync_buttons()

    def _current_smart_key(self) -> tuple[LinkKind, int] | None:
        item = self.smart_list.currentItem()
        if item is None:
            return None
        # Qt stores item data as a QVariant and hands a StrEnum back as a plain str, so
        # the value has to be put back through LinkKind before anyone compares it.
        return LinkKind(item.data(KIND_ROLE)), int(item.data(ID_ROLE))

    def _sync_buttons(self) -> None:
        index = self.tabs.currentIndex()
        if index == self.TAB_SMART:
            key = self._current_smart_key()
            linked = key is not None and self._linked.get(key, False)
            self.primary_button.setText(strings.WS_UNLINK_SHORT if linked else strings.WS_LINK)
            self.primary_button.setObjectName("" if linked else "primary")
            self.primary_button.setEnabled(key is not None)
            self.primary_button.setToolTip(strings.WS_LINK_TOOLTIP)
            self.open_button.setEnabled(key is not None)
            empty = self.smart_list.count() == 0
            self.hint.setText(
                ""
                if not empty
                else (strings.WS_SMART_NONE if self._has_tags else strings.WS_SMART_NO_TAGS)
            )
        else:
            widget = self.voices_list if index == self.TAB_VOICES else self.ideas_list
            self.primary_button.setText(strings.WS_LINK_ADD)
            self.primary_button.setToolTip("")
            self.primary_button.setObjectName("primary")
            self.primary_button.setEnabled(True)
            self.open_button.setEnabled(widget.current_id() is not None)
            parts = []
            if widget.count() == 0:
                parts.append(
                    strings.WS_VOICES_EMPTY if index == self.TAB_VOICES else strings.WS_IDEAS_EMPTY
                )
            # A linked tab lists only what is linked; say when same-tag material waits in
            # the suggestions, or a short list reads as "that is all there is".
            more = self._more[index]
            if more:
                parts.append(strings.WS_MORE_SUGGESTED.format(n=local_digits(more)))
            self.hint.setText("<br>".join(parts))
        self.hint.setVisible(bool(self.hint.text()))
        # objectName drives the primary/secondary look; re-polish after changing it.
        self.primary_button.style().unpolish(self.primary_button)
        self.primary_button.style().polish(self.primary_button)

    def _primary(self) -> None:
        index = self.tabs.currentIndex()
        if index == self.TAB_SMART:
            self._toggle_smart()
        else:
            self.add_requested.emit(LinkKind.VOICE if index == self.TAB_VOICES else LinkKind.IDEA)

    def _toggle_smart(self) -> None:
        key = self._current_smart_key()
        if key is not None:
            self.toggle_link.emit(key[0], key[1], not self._linked.get(key, False))

    def _open_current(self) -> None:
        index = self.tabs.currentIndex()
        if index == self.TAB_SMART:
            key = self._current_smart_key()
            if key is not None:
                self.open_item.emit(key[0], key[1])
            return
        widget = self.voices_list if index == self.TAB_VOICES else self.ideas_list
        item_id = widget.current_id()
        if item_id is not None:
            kind = LinkKind.VOICE if index == self.TAB_VOICES else LinkKind.IDEA
            self.open_item.emit(kind, item_id)

    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)

    # the preview -------------------------------------------------------------------------
    @property
    def previewing(self) -> bool:
        return self.pages.currentWidget() is self.preview

    def set_previewing(self, on: bool) -> None:
        self.pages.setCurrentWidget(self.preview if on else self.pages.widget(0))
        self.setMinimumWidth(PREVIEW_MIN_WIDTH if on else SIDE_PANEL_MIN_WIDTH)
        self.setMaximumWidth(PREVIEW_MAX_WIDTH if on else SIDE_PANEL_MAX_WIDTH)

    def focus_list(self) -> None:
        index = self.tabs.currentIndex()
        (self.voices_list, self.ideas_list, self.smart_list)[index].setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.smart_list and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._open_current()
                return True
            if event.key() == Qt.Key.Key_Space:
                self._toggle_smart()
                return True
        return super().eventFilter(watched, event)


@dataclass(frozen=True)
class WorkspaceState:
    """What this page was showing when the user navigated away from it."""

    episode_id: int | None = None
    note_id: int | None = None
    materials_tab: int = 0
    preview: tuple[LinkKind, int] | None = None


class EpisodeWorkspacePage(QWidget):
    episode_gone = Signal()  # the episode was deleted underneath (an undo, typically)
    episode_saved = Signal(object)  # Episode: its title, status, next action or tags changed
    number_saved = Signal()  # its place in the season's order changed
    delete_requested = Signal(int)
    list_toggle_requested = Signal()
    open_voice = Signal(int)
    open_idea = Signal(int)
    settings_requested = Signal()
    record_requested = Signal()

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self._episode: Episode | None = None
        self._notes: list[EpisodeNote] = []
        self._note: EpisodeNote | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addLayout(self._build_fields())
        body = self._body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(self._build_main(), 5)
        self.preview = MaterialPreview(workspace, events, player, jobs)
        self.preview.back_requested.connect(self.close_preview)
        self.preview.open_requested.connect(self._open_in_ideas)
        self.preview.link_requested.connect(self._link_previewed)
        self.preview.settings_requested.connect(self.settings_requested)
        self.materials = MaterialsPanel(self.preview)
        self.materials.toggle_link.connect(self._toggle_link)
        self.materials.open_item.connect(self._preview)
        self.materials.add_requested.connect(self._pick)
        body.addWidget(self.materials, 2)
        root.addLayout(body, 1)

        self._timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_note)
        self._summary_timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._summary_timer.timeout.connect(self._save_summary)
        # Ctrl+N is the Episodes page's to route (a new episode from the list, a new note
        # from in here), so it is not bound on this widget; nor is Ctrl+P, which works from
        # the list too.
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for keys, handler in (
            (QKeySequence("Ctrl+Tab"), lambda: self._cycle_note(1)),
            (QKeySequence("Ctrl+Shift+Tab"), lambda: self._cycle_note(-1)),
        ):
            QShortcut(keys, self, activated=handler, context=context)
        self._own_change = False
        events.data_changed.connect(self._on_data_changed)
        events.tags_changed.connect(self._on_data_changed)

    # layout -------------------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        """The list toggle and the identity at the start, what you act on at the end.

        «New note» is not here but over the notes it adds to, so the title keeps the width
        to be read whole."""
        header = QHBoxLayout()
        header.setSpacing(8)
        self.list_toggle = QToolButton(objectName="chromeButton")
        self.list_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_toggle.clicked.connect(self.list_toggle_requested.emit)
        header.addWidget(self.list_toggle)
        self.number_box = NumberBox(strings.EPISODE_NUMBER_TOOLTIP)
        self.number_box.number_changed.connect(self._save_number)
        header.addWidget(self.number_box)
        self.title_edit = QLineEdit(objectName="titleEdit")
        self.title_edit.setPlaceholderText(strings.EPISODE_TITLE_PLACEHOLDER)
        self.title_edit.editingFinished.connect(self._save_fields)
        header.addWidget(self.title_edit, 1)
        self.stale = QLabel(objectName="staleBadge")
        self.stale.setToolTip(strings.STALE_TOOLTIP)
        header.addWidget(self.stale)
        header.addSpacing(6)
        record = QPushButton(strings.WS_RECORD, objectName="recordButton")
        record.setToolTip(strings.WS_RECORD_TOOLTIP)
        record.clicked.connect(self.record_requested.emit)
        header.addWidget(record)
        add_key_hint(header, record, "Ctrl+R")
        prompt = QPushButton(strings.WS_SCRIPT_PROMPT)
        prompt.setToolTip(strings.WS_SCRIPT_PROMPT_TOOLTIP)
        prompt.clicked.connect(self.open_script_prompt)
        header.addWidget(prompt)
        add_key_hint(header, prompt, "Ctrl+P")
        # Rare, destructive or merely informative things stay one click away, out of the
        # row of things used every day.
        self.more_button = QToolButton(objectName="chromeButton")
        self.more_button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.more_button.setToolTip(strings.EPISODE_MORE)
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_button.setMenu(self.more_menu)
        header.addWidget(self.more_button)
        return header

    def _fill_more_menu(self) -> None:
        menu = self.more_menu
        menu.clear()
        episode = self._episode
        if episode is None or episode.id is None:
            return
        for line in (
            strings.CREATED_AT.format(when=format_datetime(episode.created_at)),
            strings.UPDATED_AT.format(when=format_datetime(episode.updated_at)),
        ):
            menu.addAction(line).setEnabled(False)
        menu.addSeparator()
        episode_id = episode.id
        menu.addAction(strings.EPISODE_DELETE, lambda: self.delete_requested.emit(episode_id))

    def _build_fields(self) -> QGridLayout:
        """Where the episode stands: its stage on one line, the next action on its own
        line below — the one sentence that drives the episode, never squeezed down to a
        word beside the stage — then its tags, where chips can run the full width instead
        of piling up in a corner. (The stage sits here and not in the header so the title
        keeps enough width to be read whole.)"""
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.status_box = QComboBox()
        self.status_box.setToolTip(strings.EPISODE_STATUS)
        self.status_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for status in EpisodeStatus:
            self.status_box.addItem(strings.STATUS_LABELS[status], status)
        self.status_box.activated.connect(lambda _i: self._save_fields())
        self.season_box = QComboBox()
        self.season_box.setToolTip(strings.SEASON_LABEL)
        self.season_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.season_box.activated.connect(lambda _i: self._save_season())
        self.publish_button = PublishChecklistButton(self._ws)
        self.publish_button.saved.connect(self._on_publish_saved)
        self.next_action = QLineEdit(objectName="nextAction")
        self.next_action.setPlaceholderText(strings.EPISODE_NEXT_ACTION_PLACEHOLDER)
        self.next_action.editingFinished.connect(self._save_fields)
        self.tag_input = TagInput(self._ws.tags, self._events)
        self.tag_input.tags_changed.connect(self._save_tags)
        self.summary = QPlainTextEdit()
        self.summary.setPlaceholderText(strings.EPISODE_SUMMARY_PLACEHOLDER)
        self.summary.setTabChangesFocus(True)
        self.summary.setFixedHeight(self.summary.fontMetrics().lineSpacing() * SUMMARY_LINES + 18)
        self.summary.textChanged.connect(self._schedule_summary)
        line = self.next_action.sizeHint().height()

        def label(text: str) -> QLabel:
            widget = QLabel(text, objectName="fieldLabel")
            widget.setMinimumHeight(line)  # level with the field's first line
            widget.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading)
            return widget

        top = Qt.AlignmentFlag.AlignTop
        grid.addWidget(label(strings.EPISODE_STATUS), 0, 0, top)
        stage = QHBoxLayout()
        stage.setSpacing(10)
        stage.addWidget(self.status_box)
        stage.addSpacing(10)
        stage.addWidget(label(strings.SEASON_LABEL))
        stage.addWidget(self.season_box)
        stage.addSpacing(10)
        stage.addWidget(self.publish_button)
        stage.addStretch(1)
        grid.addLayout(stage, 0, 1)
        grid.addWidget(label(strings.EPISODE_NEXT_ACTION), 1, 0, top)
        grid.addWidget(self.next_action, 1, 1)
        grid.addWidget(label(strings.TAG_LABEL), 2, 0, top)
        grid.addWidget(self.tag_input, 2, 1)
        grid.addWidget(label(strings.EPISODE_SUMMARY), 3, 0, top)
        grid.addWidget(self.summary, 3, 1)
        grid.setColumnStretch(1, 1)
        return grid

    def _build_main(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(QLabel(strings.WS_NOTES, objectName="sectionTitle"))
        self.tabs = QTabBar(objectName="noteTabs")
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tabs_row.addWidget(self.tabs, 1)
        self.new_note_button = QPushButton(strings.WS_NOTE_NEW, objectName="primary")
        self.new_note_button.setToolTip("Ctrl+N")
        self.new_note_button.clicked.connect(self.new_note)
        tabs_row.addWidget(self.new_note_button)
        col.addLayout(tabs_row)

        self.note_stack = QStackedWidget()
        empty = QLabel(strings.WS_NOTES_EMPTY, objectName="emptyHint")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.note_stack.addWidget(empty)
        editor = QFrame()
        ed = QVBoxLayout(editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        self.note_title = QLineEdit(objectName="noteTitle")
        self.note_title.setPlaceholderText(strings.WS_NOTE_TITLE_PLACEHOLDER)
        self.note_title.textEdited.connect(lambda _t: self._schedule_save())
        self.note_title.returnPressed.connect(self._focus_body)
        ed.addWidget(self.note_title)
        self.note_body = QPlainTextEdit(objectName="noteBody")
        self.note_body.setPlaceholderText(strings.WS_NOTE_BODY_PLACEHOLDER)
        self.note_body.setTabChangesFocus(True)
        self.note_body.textChanged.connect(self._schedule_save)
        ed.addWidget(self.note_body, 1)
        foot = QHBoxLayout()
        self.note_meta = QLabel(objectName="muted")
        foot.addWidget(self.note_meta)
        foot.addStretch(1)
        delete = QPushButton(strings.WS_NOTE_DELETE, objectName="danger")
        delete.clicked.connect(self._delete_note)
        foot.addWidget(delete)
        ed.addLayout(foot)
        self.note_stack.addWidget(editor)
        col.addWidget(self.note_stack, 1)
        return col

    # public -------------------------------------------------------------------------------
    @property
    def episode_id(self) -> int | None:
        return None if self._episode is None else self._episode.id

    def focus_main(self) -> None:
        """Put the caret where work continues: the open note, else "New note"."""
        if self._note is not None:
            self.note_body.setFocus()
        else:
            self.new_note_button.setFocus()

    def clear(self) -> None:
        """No episode selected (the list is empty, or its selection was deleted)."""
        self.flush()
        self.close_preview(focus=False)
        self._episode = None
        self._note = None
        self._notes = []

    # navigation state ---------------------------------------------------------------------
    def nav_state(self) -> WorkspaceState:
        return WorkspaceState(
            episode_id=self.episode_id,
            note_id=self._note.id if self._note is not None else None,
            materials_tab=self.materials.tabs.currentIndex(),
            preview=self.preview.item if self.materials.previewing else None,
        )

    def restore_nav_state(self, state: object) -> None:
        if not isinstance(state, WorkspaceState) or state.episode_id is None:
            return
        if state.episode_id != self.episode_id:
            if not self.open(state.episode_id, state.note_id):
                return
        elif state.note_id is not None:
            self._load_notes(select_id=state.note_id)
        self.materials.show_tab(state.materials_tab)
        if state.preview is not None:
            self._preview(*state.preview, focus=False)
        else:
            self.close_preview(focus=False)

    def open(self, episode_id: int, note_id: int | None = None, focus: bool = False) -> bool:
        """Show an episode (it counts as opening it, for the resume screen).

        Focus moves in only when asked: choosing a row in the list must leave the caret
        in the list, so the arrow keys keep walking through the episodes.
        """
        self.flush()
        if episode_id != self.episode_id:
            self.close_preview(focus=False)  # another episode's material
        try:
            self._episode = self._ws.episodes.open(episode_id)
        except Exception as exc:
            show_error(self, exc)
            return False
        self._fill_fields()
        self._load_notes(select_id=note_id)
        self._refresh_links()
        if focus:
            self.focus_main()
            if note_id is not None and self._note is not None:
                self.note_body.moveCursor(self.note_body.textCursor().MoveOperation.End)
        return True

    def reload(self, note_id: int | None = None) -> None:
        """Read the episode again after it changed underneath us (an undo, typically).

        Unlike `open`, it does not count as opening the episode and keeps the page
        where it is; if the episode itself is gone, it steps back out.
        """
        if self._episode is None or self._episode.id is None:
            return
        episode_id = self._episode.id
        self.flush()
        try:
            self._episode = self._ws.episodes.get(episode_id)
        except NotFoundError:
            self._episode = None
            self.episode_gone.emit()
            return
        self._fill_fields()
        self._load_notes(select_id=note_id)
        self._refresh_links()

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._save_note()
        if self._summary_timer.isActive():
            self._summary_timer.stop()
            self._save_summary()

    def new_note(self) -> None:
        if self._episode is None or self._episode.id is None:
            return
        self.flush()
        try:
            note = self._ws.episode_notes.create(self._episode.id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed()
        self._load_notes(select_id=note.id)
        self.note_title.setFocus()

    def open_script_prompt(self) -> None:
        """The brief and the prompt it makes, from what the episode holds right now."""
        episode = self._episode
        if episode is None or episode.id is None:
            return
        self.flush()  # the note being typed is part of the draft
        try:
            material = self._ws.script_prompt.material(episode.id)
        except Exception as exc:
            show_error(self, exc)
            return
        dialog = ScriptPromptDialog(self, self._ws, episode, material)
        dialog.exec()
        if dialog.changed:
            self._reload_episode()
            self._changed()

    # episode fields ---------------------------------------------------------------------
    def _fill_fields(self) -> None:
        episode = self._episode
        if episode is None:
            return
        self.title_edit.setText(episode.title)
        self.title_edit.setCursorPosition(0)  # show where the title starts, not where it ends
        self.number_box.set_number(episode.number)
        self.status_box.setCurrentIndex(self.status_box.findData(episode.status))
        self.next_action.setText(episode.next_action)
        self._fill_seasons(episode.season_id)
        self.tag_input.set_tag_ids(episode.tag_ids)
        if self.summary.toPlainText() != episode.summary:  # keep the caret while typing
            self._loading = True
            self.summary.setPlainText(episode.summary)
            self._loading = False
        self.publish_button.set_episode(episode)
        badge = stale_text(episode)
        self.stale.setText(badge)
        self.stale.setVisible(bool(badge))

    def _reload_episode(self) -> None:
        if self._episode is None or self._episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.get(self._episode.id)
        except NotFoundError:
            self._episode = None
            self.episode_gone.emit()
            return
        self.episode_saved.emit(self._episode)
        badge = stale_text(self._episode)
        self.stale.setText(badge)
        self.stale.setVisible(bool(badge))

    def _save_fields(self) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            saved = self._ws.episodes.update(
                episode.id,
                title=self.title_edit.text(),
                # Qt hands a StrEnum back as a plain str.
                status=EpisodeStatus(self.status_box.currentData()),
                next_action=self.next_action.text(),
            )
        except Exception as exc:
            show_error(self, exc)
            self._fill_fields()
            return
        if saved.updated_at != episode.updated_at:
            self._episode = saved
            self._fill_fields()
            self.episode_saved.emit(saved)
            self._changed()

    def _save_number(self, number: int | None) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.set_number(episode.id, number)
        except Exception as exc:
            show_error(self, exc)
            self.number_box.set_number(episode.number)
            return
        self.number_saved.emit()
        self._changed()

    def _schedule_summary(self) -> None:
        if not self._loading and self._episode is not None:
            self._summary_timer.start()

    def _save_summary(self) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            saved = self._ws.episodes.set_summary(episode.id, self.summary.toPlainText())
        except Exception as exc:
            show_error(self, exc)
            return
        if saved.updated_at != episode.updated_at:
            self._reload_episode()
            self._changed()

    def _on_publish_saved(self, episode: Episode) -> None:
        self._episode = episode
        self.episode_saved.emit(episode)
        self._changed()
        badge = stale_text(episode)
        self.stale.setText(badge)
        self.stale.setVisible(bool(badge))

    def _fill_seasons(self, current: int | None) -> None:
        box = self.season_box
        box.blockSignals(True)
        box.clear()
        box.addItem(strings.SEASON_NONE, None)
        try:
            seasons = self._ws.seasons.list_all()
        except Exception:
            log_swallowed("season choices")
            seasons = []
        for season in seasons:
            box.addItem(numbered(season.title, season.number), season.id)
        box.insertSeparator(box.count())
        box.addItem(strings.SEASON_NEW, NEW_SEASON)
        box.setCurrentIndex(max(0, box.findData(current)))
        box.blockSignals(False)

    def _save_season(self) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        season_id = self.season_box.currentData()
        if season_id == NEW_SEASON:
            season = create_season(self, self._ws)
            if season is None:
                self._fill_seasons(episode.season_id)
                return
            season_id = season.id
        try:
            self._episode = self._ws.episodes.set_season(episode.id, season_id)
        except Exception as exc:
            show_error(self, exc)
        self._fill_fields()
        self.episode_saved.emit(self._episode)
        self._changed()

    def _save_tags(self, tag_ids: list[int]) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.set_tags(episode.id, tag_ids)
        except Exception as exc:
            show_error(self, exc)
            self.tag_input.set_tag_ids(episode.tag_ids)
            return
        self.episode_saved.emit(self._episode)
        self._changed()
        self._refresh_links()

    # notes ------------------------------------------------------------------------------
    def _load_notes(self, select_id: int | None = None) -> None:
        if self._episode is None or self._episode.id is None:
            return
        keep = select_id if select_id is not None else (self._note.id if self._note else None)
        try:
            self._notes = self._ws.episode_notes.list_for_episode(self._episode.id)
        except Exception as exc:
            show_error(self, exc)
            self._notes = []
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        index = -1
        for i, note in enumerate(self._notes):
            self.tabs.addTab(note_label(note))
            self.tabs.setTabToolTip(i, note_label(note))
            if note.id == keep:
                index = i
        if index < 0 and self._notes:
            # default: the most recently edited note
            latest = max(self._notes, key=lambda n: n.updated_at)
            index = self._notes.index(latest)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self._show_note(self._notes[index] if index >= 0 else None)

    def _show_note(self, note: EpisodeNote | None) -> None:
        same = note is not None and self._note is not None and note.id == self._note.id
        self._note = note
        self.note_stack.setCurrentIndex(0 if note is None else 1)
        if note is None:
            return
        self._loading = True
        # Re-showing the note already in the editor (a reload) must not throw away the
        # caret and the scroll position when nothing in it changed.
        if not (same and self.note_title.text() == note.title):
            self.note_title.setText(note.title)
        if not (same and self.note_body.toPlainText() == note.body):
            self.note_body.setPlainText(note.body)
        self._loading = False
        self._update_note_meta(note)

    def _update_note_meta(self, note: EpisodeNote) -> None:
        self.note_meta.setText(strings.UPDATED_AT.format(when=format_datetime(note.updated_at)))

    def _on_tab_changed(self, index: int) -> None:
        self.flush()
        self._show_note(self._notes[index] if 0 <= index < len(self._notes) else None)

    def _cycle_note(self, step: int) -> None:
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def _focus_body(self) -> None:
        self.note_body.setFocus()

    def _schedule_save(self) -> None:
        if not self._loading and self._note is not None:
            self._timer.start()

    def _save_note(self) -> None:
        note = self._note
        if note is None or note.id is None:
            return
        try:
            saved = self._ws.episode_notes.update(
                note.id, self.note_title.text(), self.note_body.toPlainText()
            )
        except Exception as exc:
            show_error(self, exc)
            return
        if saved.updated_at == note.updated_at:
            return
        self._note = saved
        for i, existing in enumerate(self._notes):
            if existing.id == saved.id:
                self._notes[i] = saved
                self.tabs.setTabText(i, note_label(saved))
                self.tabs.setTabToolTip(i, note_label(saved))
        self._update_note_meta(saved)
        self._reload_episode()
        self._changed()

    def _delete_note(self) -> None:
        note = self._note
        if note is None or note.id is None:
            return
        if not confirm(self, strings.WS_NOTE_DELETE_CONFIRM.format(title=note_label(note))):
            return
        self._timer.stop()
        try:
            self._ws.episode_notes.delete(note.id)
        except Exception as exc:
            show_error(self, exc)
        self._note = None
        self._changed()
        self._load_notes()

    # links ------------------------------------------------------------------------------
    def _refresh_links(self) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            voices = {v.id: v for v in self._ws.voices.list_all()}
            ideas = {i.id: i for i in self._ws.ideas.list_all()}
            links = self._ws.episodes.smart_links(episode.id)
        except Exception as exc:
            show_error(self, exc)
            return
        names: dict[tuple[LinkKind, int], str] = {}
        for vid, voice in voices.items():
            if vid is not None:
                names[(LinkKind.VOICE, vid)] = Path(voice.file_path).name
        for iid, idea in ideas.items():
            if iid is not None:
                names[(LinkKind.IDEA, iid)] = _first_line(idea.text)

        # Most shared tags first, as in the suggestions; then the most recent.
        wanted = episode.tag_ids

        def shared(tag_ids: set[int]) -> int:
            return len(tag_ids & wanted)

        def shared_text(tag_ids: set[int]) -> str:
            n = shared(tag_ids)
            return strings.WS_SHARED.format(n=local_digits(n)) if n else ""

        linked_voices = [voices[v] for v in episode.voice_ids if v in voices]
        linked_voices.sort(key=lambda v: (-shared(v.tag_ids), -v.imported_at.timestamp()))
        voice_rows: list[tuple[int, str, str]] = []
        for voice in linked_voices:
            if voice.id is None:
                continue
            parts = [
                strings.ARCHIVED_BADGE if voice.archived else "",
                shared_text(voice.tag_ids),
                format_duration(voice.duration_ms),
                voice.format.upper(),
            ]
            voice_rows.append(
                (voice.id, Path(voice.file_path).name, "  ·  ".join(p for p in parts if p))
            )
        self.materials.show_linked(LinkKind.VOICE, voice_rows)

        idea_rows: list[tuple[int, str, str]] = []
        linked_ideas = [ideas[i] for i in episode.idea_note_ids if i in ideas]
        linked_ideas.sort(key=lambda i: (-shared(i.tag_ids), -i.updated_at.timestamp()))
        for idea in linked_ideas:
            if idea.id is None:
                continue
            tag_names = [t.name for t in self._ws.tags.by_ids(idea.tag_ids)]
            parts = [
                strings.ARCHIVED_BADGE if idea.archived else "",
                shared_text(idea.tag_ids),
                strings.LIST_SEPARATOR.join(tag_names),
            ]
            idea_rows.append((idea.id, _first_line(idea.text), "  ·  ".join(p for p in parts if p)))
        self.materials.show_linked(LinkKind.IDEA, idea_rows)

        linked = {(LinkKind.VOICE, v) for v in episode.voice_ids} | {
            (LinkKind.IDEA, i) for i in episode.idea_note_ids
        }
        tag_names_by_id = {t.id: t.name for t in self._ws.tags.list_all() if t.id is not None}
        self.materials.show_links(links, names, tag_names_by_id, linked, bool(episode.tag_ids))
        previewed = self.preview.item
        if self.materials.previewing and previewed is not None:
            if previewed not in names:  # it went to the trash meanwhile
                self.close_preview(focus=False)
            else:
                self.preview.set_linked(previewed in linked)

    def _toggle_link(self, kind: LinkKind, item_id: int, link: bool) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.link(episode.id, kind, item_id, link)
        except Exception as exc:
            show_error(self, exc)
            return
        self._changed()
        self._reload_episode()
        self._refresh_links()

    def _pick(self, kind: LinkKind) -> None:
        episode = self._episode
        if episode is None or episode.id is None:
            return
        rows: list[tuple[int, str, str]]
        if kind is LinkKind.VOICE:
            title = strings.WS_PICK_VOICE
            rows = [
                (v.id, Path(v.file_path).name, format_duration(v.duration_ms))
                for v in self._ws.voices.list_all(ArchiveScope.ACTIVE)
                if v.id is not None and v.id not in episode.voice_ids
            ]
        else:
            title = strings.WS_PICK_IDEA
            rows = [
                (
                    i.id,
                    _first_line(i.text),
                    strings.LIST_SEPARATOR.join(t.name for t in self._ws.tags.by_ids(i.tag_ids)),
                )
                for i in self._ws.ideas.list_all(ArchiveScope.ACTIVE)
                if i.id is not None and i.id not in episode.idea_note_ids
            ]
        dialog = PickerDialog(self, title, rows)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for item_id in dialog.chosen():
            self._toggle_link(kind, item_id, True)

    # the preview --------------------------------------------------------------------------
    def _preview(self, kind: LinkKind, item_id: int, focus: bool = True) -> None:
        episode = self._episode
        if episode is None:
            return
        ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
        if not self.preview.show_item(kind, item_id, item_id in ids):
            self.close_preview(focus=False)
            return
        self.materials.set_previewing(True)
        # As wide as the note while it is open: reading and writing side by side.
        self._body.setStretch(0, 1)
        self._body.setStretch(1, 1)
        if focus:
            self.preview.focus()

    def close_preview(self, focus: bool = True) -> None:
        if not self.materials.previewing:
            return
        self.preview.close_item()
        self.materials.set_previewing(False)
        self._body.setStretch(0, 5)
        self._body.setStretch(1, 2)
        if focus:
            self.materials.focus_list()

    def _link_previewed(self, kind: LinkKind, item_id: int) -> None:
        self._toggle_link(kind, item_id, True)

    def _open_in_ideas(self, kind: LinkKind, item_id: int) -> None:
        self.flush()
        if kind is LinkKind.VOICE:
            self.open_voice.emit(item_id)
        else:
            self.open_idea.emit(item_id)

    # lifecycle ----------------------------------------------------------------------------
    def _changed(self) -> None:
        self._own_change = True
        try:
            self._events.data_changed.emit()
        finally:
            self._own_change = False

    def _on_data_changed(self) -> None:
        # Changes made elsewhere (tags on a voice, a new idea...) can change the suggestions.
        if self.isVisible() and not self._own_change:
            self._refresh_links()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._episode is not None:
            self._reload_episode()
            self._refresh_links()

    def hideEvent(self, event: QHideEvent) -> None:
        self.flush()
        super().hideEvent(event)
