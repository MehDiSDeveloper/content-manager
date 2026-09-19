"""Episode workspace: one view for an episode's notes, linked material, status and next action,
plus the smart-link side panel (Voices and IdeaNotes sharing its tags).

Layout (RTL): header row, next action + tags, then [main column | smart-link panel].
Main column: note tabs + editor, and below it the linked voices / linked ideas lists.
"""

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
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

from podcast_workspace.domain.entities import Episode, EpisodeNote, EpisodeStatus
from podcast_workspace.domain.pipeline import days_untouched, is_stale
from podcast_workspace.domain.smart_links import LinkKind, SmartLink
from podcast_workspace.domain.text import normalize_for_match
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.base import SUBTITLE_ROLE, TwoLineDelegate
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    fa_digits,
    format_datetime,
    format_duration,
    show_error,
)
from podcast_workspace.ui.widgets.tag_input import TagInput

AUTOSAVE_DELAY_MS = 700
SIDE_PANEL_WIDTH = 300
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
    return strings.STALE_BADGE.format(days=fa_digits(days_untouched(episode, now)))


class _LinkedList(QListWidget):
    """Linked voices or ideas. Click/Enter opens, Delete unlinks."""

    open_item = Signal(int)
    unlink_item = Signal(int)

    def __init__(self) -> None:
        super().__init__(objectName="linkedList")
        self.setItemDelegate(TwoLineDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: self.open_item.emit(int(item.data(ID_ROLE))))

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


class PickerDialog(QDialog):
    """Choose voices or ideas to link: type to filter, Enter adds the selection."""

    def __init__(self, parent: QWidget, title: str, rows: list[tuple[int, str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 520)
        self._rows = rows
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(12)
        col.addWidget(QLabel(title, objectName="dialogTitle"))
        self.filter = QLineEdit(placeholderText=strings.WS_PICK_FILTER)
        self.filter.textChanged.connect(self._fill)
        self.filter.installEventFilter(self)
        col.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        col.addWidget(self.list, 1)
        buttons = QDialogButtonBox()
        add = buttons.addButton(strings.WS_PICK_ADD, QDialogButtonBox.ButtonRole.AcceptRole)
        add.setObjectName("primary")
        buttons.addButton(strings.CANCEL, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._fill("")

    def _fill(self, query: str) -> None:
        needle = normalize_for_match(query)
        self.list.clear()
        for item_id, title, subtitle in self._rows:
            if needle and needle not in normalize_for_match(f"{title} {subtitle}"):
                continue
            item = QListWidgetItem(title)
            item.setData(ID_ROLE, item_id)
            item.setData(SUBTITLE_ROLE, subtitle)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            empty = QListWidgetItem(strings.WS_PICK_EMPTY)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)

    def chosen(self) -> list[int]:
        return [int(i.data(ID_ROLE)) for i in self.list.selectedItems() if i.data(ID_ROLE)]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.filter and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.list.setFocus()
                self.list.keyPressEvent(event)
                return True
        return super().eventFilter(watched, event)


class SmartLinkPanel(QFrame):
    toggle_link = Signal(object, int, bool)  # LinkKind, item_id, link?
    open_item = Signal(object, int)  # LinkKind, item_id

    def __init__(self) -> None:
        super().__init__(objectName="sidePanel")
        self.setFixedWidth(SIDE_PANEL_WIDTH)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(10)
        col.addWidget(QLabel(strings.WS_SMART, objectName="sectionTitle"))
        self.hint = QLabel(objectName="muted")
        self.hint.setWordWrap(True)
        col.addWidget(self.hint)
        self.list = QListWidget(objectName="smartList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(lambda _i: self._toggle_current())
        self.list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self.list.installEventFilter(self)
        col.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.link_button = QPushButton(strings.WS_LINK)
        self.link_button.clicked.connect(self._toggle_current)
        buttons.addWidget(self.link_button, 1)
        self.open_button = QPushButton(strings.WS_OPEN.split(" (")[0])
        self.open_button.clicked.connect(self._open_current)
        buttons.addWidget(self.open_button)
        col.addLayout(buttons)
        self._linked: dict[tuple[LinkKind, int], bool] = {}

    def show_links(
        self,
        links: list[SmartLink],
        names: dict[tuple[LinkKind, int], str],
        tag_names: dict[int, str],
        linked: set[tuple[LinkKind, int]],
        has_tags: bool,
    ) -> None:
        current = self._current_key()
        self.list.clear()
        self._linked = {}
        target = None
        for link in links:
            key = (link.kind, link.item_id)
            shared = "، ".join(sorted(tag_names.get(t, "?") for t in link.shared_tag_ids))
            kind = strings.KIND_VOICE if link.kind is LinkKind.VOICE else strings.KIND_IDEA
            subtitle = strings.WS_SMART_SUBTITLE.format(
                kind=kind, n=fa_digits(link.score), names=shared
            )
            is_linked = key in linked
            if is_linked:
                subtitle = strings.WS_SMART_LINKED + "، " + subtitle
            item = QListWidgetItem(names.get(key, "?"))
            item.setData(ID_ROLE, link.item_id)
            item.setData(KIND_ROLE, link.kind)
            item.setData(SUBTITLE_ROLE, subtitle)
            item.setToolTip(subtitle)
            self.list.addItem(item)
            self._linked[key] = is_linked
            if key == current:
                target = item
        if target is not None:
            self.list.setCurrentItem(target)
        elif self.list.count():
            self.list.setCurrentRow(0)
        self.hint.setText(
            "" if links else (strings.WS_SMART_NONE if has_tags else strings.WS_SMART_NO_TAGS)
        )
        self.hint.setVisible(not links)
        self._sync_buttons()

    def _current_key(self) -> tuple[LinkKind, int] | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(KIND_ROLE), int(item.data(ID_ROLE))

    def _sync_buttons(self) -> None:
        key = self._current_key()
        self.link_button.setEnabled(key is not None)
        self.open_button.setEnabled(key is not None)
        linked = key is not None and self._linked.get(key, False)
        self.link_button.setText(strings.WS_UNLINK_SHORT if linked else strings.WS_LINK)

    def _toggle_current(self) -> None:
        key = self._current_key()
        if key is not None:
            self.toggle_link.emit(key[0], key[1], not self._linked.get(key, False))

    def _open_current(self) -> None:
        key = self._current_key()
        if key is not None:
            self.open_item.emit(key[0], key[1])

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.list and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._toggle_current()
                return True
        return super().eventFilter(watched, event)


class EpisodeWorkspacePage(QWidget):
    back_requested = Signal()
    open_voice = Signal(int)
    open_idea = Signal(int)
    settings_requested = Signal()
    record_requested = Signal()

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self._episode: Episode | None = None
        self._notes: list[EpisodeNote] = []
        self._note: EpisodeNote | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 20, 32, 24)
        root.setSpacing(14)
        root.addLayout(self._build_header())
        root.addLayout(self._build_fields())
        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(self._build_main(), 1)
        self.smart = SmartLinkPanel()
        self.smart.toggle_link.connect(self._toggle_link)
        self.smart.open_item.connect(self._open_linked)
        body.addWidget(self.smart)
        root.addLayout(body, 1)

        self._timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_note)
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for keys, handler in (
            (QKeySequence(QKeySequence.StandardKey.New), self.new_note),
            (QKeySequence("Ctrl+R"), self.record_requested.emit),
            (QKeySequence("Ctrl+Tab"), lambda: self._cycle_note(1)),
            (QKeySequence("Ctrl+Shift+Tab"), lambda: self._cycle_note(-1)),
        ):
            QShortcut(keys, self, activated=handler, context=context)
        self._own_change = False
        events.data_changed.connect(self._on_data_changed)
        events.tags_changed.connect(self._on_data_changed)

    # layout -------------------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        back = QToolButton(objectName="backButton")
        back.setText("→  " + strings.WS_BACK)
        back.setToolTip(strings.WS_BACK_TOOLTIP)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self._go_back)
        header.addWidget(back)
        self.title_edit = QLineEdit(objectName="titleEdit")
        self.title_edit.setPlaceholderText(strings.EPISODE_TITLE_PLACEHOLDER)
        self.title_edit.editingFinished.connect(self._save_fields)
        header.addWidget(self.title_edit, 1)
        self.stale = QLabel(objectName="staleBadge")
        self.stale.setToolTip(strings.STALE_TOOLTIP)
        header.addWidget(self.stale)
        self.status_box = QComboBox()
        for status in EpisodeStatus:
            self.status_box.addItem(strings.STATUS_LABELS[status], status)
        self.status_box.activated.connect(lambda _i: self._save_fields())
        header.addWidget(self.status_box)
        record = QPushButton(strings.WS_RECORD, objectName="recordButton")
        record.setToolTip(strings.WS_RECORD_TOOLTIP)
        record.clicked.connect(self.record_requested.emit)
        header.addWidget(record)
        self.new_note_button = QPushButton(strings.WS_NOTE_NEW, objectName="primary")
        self.new_note_button.setToolTip("Ctrl+N")
        self.new_note_button.clicked.connect(self.new_note)
        header.addWidget(self.new_note_button)
        return header

    def _build_fields(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(strings.EPISODE_NEXT_ACTION))
        self.next_action = QLineEdit(objectName="nextAction")
        self.next_action.setPlaceholderText(strings.EPISODE_NEXT_ACTION_PLACEHOLDER)
        self.next_action.editingFinished.connect(self._save_fields)
        row.addWidget(self.next_action, 3)
        row.addSpacing(8)
        row.addWidget(QLabel(strings.TAG_LABEL))
        self.tag_input = TagInput(self._ws.tags, self._events)
        self.tag_input.tags_changed.connect(self._save_tags)
        row.addWidget(self.tag_input, 2)
        return row

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
        col.addWidget(self.note_stack, 3)

        linked = QHBoxLayout()
        linked.setSpacing(16)
        self.voices_list, voices_box = self._linked_box(strings.WS_LINKED_VOICES, LinkKind.VOICE)
        self.ideas_list, ideas_box = self._linked_box(strings.WS_LINKED_IDEAS, LinkKind.IDEA)
        linked.addLayout(voices_box, 1)
        linked.addLayout(ideas_box, 1)
        col.addLayout(linked, 2)
        return col

    def _linked_box(self, title: str, kind: LinkKind) -> tuple[_LinkedList, QVBoxLayout]:
        box = QVBoxLayout()
        box.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(QLabel(title, objectName="sectionTitle"))
        head.addStretch(1)
        add = QPushButton(strings.WS_LINK_ADD, objectName="flatButton")
        add.clicked.connect(lambda: self._pick(kind))
        head.addWidget(add)
        box.addLayout(head)
        lst = _LinkedList()
        lst.open_item.connect(lambda item_id: self._open_linked(kind, item_id))
        lst.unlink_item.connect(lambda item_id: self._toggle_link(kind, item_id, False))
        box.addWidget(lst, 1)
        return lst, box

    # public -------------------------------------------------------------------------------
    @property
    def episode_id(self) -> int | None:
        return None if self._episode is None else self._episode.id

    def open(self, episode_id: int, note_id: int | None = None) -> bool:
        self.flush()
        try:
            self._episode = self._ws.episodes.open(episode_id)
        except Exception as exc:
            show_error(self, exc)
            return False
        self._fill_fields()
        self._load_notes(select_id=note_id)
        self._refresh_links()
        if note_id is not None and self._note is not None:
            self.note_body.setFocus()
            self.note_body.moveCursor(self.note_body.textCursor().MoveOperation.End)
        elif self._note is None:
            self.new_note_button.setFocus()
        return True

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._save_note()

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

    # episode fields ---------------------------------------------------------------------
    def _fill_fields(self) -> None:
        episode = self._episode
        if episode is None:
            return
        self.title_edit.setText(episode.title)
        self.status_box.setCurrentIndex(self.status_box.findData(episode.status))
        self.next_action.setText(episode.next_action)
        self.tag_input.set_tag_ids(episode.tag_ids)
        badge = stale_text(episode)
        self.stale.setText(badge)
        self.stale.setVisible(bool(badge))

    def _reload_episode(self) -> None:
        if self._episode is None or self._episode.id is None:
            return
        try:
            self._episode = self._ws.episodes.get(self._episode.id)
        except Exception:
            self._episode = None
            self.back_requested.emit()
            return
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
                status=self.status_box.currentData(),
                next_action=self.next_action.text(),
            )
        except Exception as exc:
            show_error(self, exc)
            self._fill_fields()
            return
        if saved.updated_at != episode.updated_at:
            self._episode = saved
            self._fill_fields()
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
        self._note = note
        self.note_stack.setCurrentIndex(0 if note is None else 1)
        if note is None:
            return
        self._loading = True
        self.note_title.setText(note.title)
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

        self.voices_list.clear()
        for vid in sorted(episode.voice_ids, key=lambda i: names.get((LinkKind.VOICE, i), "")):
            voice = voices.get(vid)
            if voice is None:
                continue
            item = QListWidgetItem(Path(voice.file_path).name)
            item.setData(ID_ROLE, vid)
            item.setData(
                SUBTITLE_ROLE, f"{format_duration(voice.duration_ms)}  ·  {voice.format.upper()}"
            )
            self.voices_list.addItem(item)
        self.ideas_list.clear()
        linked_ideas = [ideas[i] for i in episode.idea_note_ids if i in ideas]
        for idea in sorted(linked_ideas, key=lambda i: i.updated_at, reverse=True):
            iid = idea.id
            item = QListWidgetItem(_first_line(idea.text))
            item.setData(ID_ROLE, iid)
            tag_names = [t.name for t in self._ws.tags.by_ids(idea.tag_ids)]
            item.setData(SUBTITLE_ROLE, "، ".join(tag_names))
            self.ideas_list.addItem(item)

        linked = {(LinkKind.VOICE, v) for v in episode.voice_ids} | {
            (LinkKind.IDEA, i) for i in episode.idea_note_ids
        }
        tag_names = {t.id: t.name for t in self._ws.tags.list_all() if t.id is not None}
        self.smart.show_links(links, names, tag_names, linked, bool(episode.tag_ids))

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
                for v in self._ws.voices.list_all()
                if v.id is not None and v.id not in episode.voice_ids
            ]
        else:
            title = strings.WS_PICK_IDEA
            rows = [
                (
                    i.id,
                    _first_line(i.text),
                    "، ".join(t.name for t in self._ws.tags.by_ids(i.tag_ids)),
                )
                for i in self._ws.ideas.list_all()
                if i.id is not None and i.id not in episode.idea_note_ids
            ]
        dialog = PickerDialog(self, title, rows)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for item_id in dialog.chosen():
            self._toggle_link(kind, item_id, True)

    def _open_linked(self, kind: LinkKind, item_id: int) -> None:
        self.flush()
        if kind is LinkKind.VOICE:
            self.open_voice.emit(item_id)
        else:
            self.open_idea.emit(item_id)

    # lifecycle ----------------------------------------------------------------------------
    def _go_back(self) -> None:
        self.flush()
        self.back_requested.emit()

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
