"""Episodes, Voices and Ideas pages: create, list, edit (autosave), delete."""

import subprocess
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QHideEvent,
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Episode, IdeaNote, Season, Voice
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import ImportReport
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.icons import NAV_ICON_SIZE, list_pane_icon, more_icon
from podcast_workspace.ui.pages.base import ListPage, ListPageState, Row
from podcast_workspace.ui.pages.episode_workspace import EpisodeWorkspacePage, stale_text
from podcast_workspace.ui.player.player_widget import PlayerWidget, install_player_keys
from podcast_workspace.ui.player.timestamp_panel import TimestampPanel
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs, TranscriptPanel
from podcast_workspace.ui.seasons import create_season, rename_season
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    format_datetime,
    format_duration,
    local_digits,
    run_async,
    show_error,
)
from podcast_workspace.ui.widgets.tag_input import TagInput

AUTOSAVE_DELAY_MS = 700
SEASON_ALL, SEASON_NONE = "all", "none"  # the season box's two fixed entries
MINI_LIST_HEIGHT = 208


def _danger_button(text: str) -> QPushButton:
    return QPushButton(text, objectName="danger")


def _first_line(text: str, width: int = 70) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


def _tag_map(workspace: Workspace) -> dict[int, str]:
    """id -> name for every tag, read once per list rebuild instead of once per row."""
    return {t.id: t.name for t in workspace.tags.list_all() if t.id is not None}


def _tag_labels(
    workspace: Workspace, tag_ids: Iterable[int], known: dict[int, str] | None = None
) -> tuple[str, ...]:
    """The names a row carries, for the filter box and the subtitle. `known` is the map
    from `_tag_map`; without one this falls back to the service (a single row redrawn
    after an edit, where a tag just created is not in any map yet)."""
    if known is None:
        return tuple(t.name for t in workspace.tags.by_ids(tag_ids))
    return tuple(name for name in (known.get(i) for i in tag_ids) if name)


class PathLabel(QLabel):
    """One muted line showing a file path, elided in the middle, copied on click."""

    def __init__(self) -> None:
        super().__init__(objectName="muted")
        self._path = ""
        self.setToolTip(strings.VOICE_PATH_TOOLTIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(120)

    def set_path(self, path: str) -> None:
        self._path = path
        self._elide()

    def _elide(self) -> None:
        self.setText(
            self.fontMetrics().elidedText(self._path, Qt.TextElideMode.ElideMiddle, self.width())
        )

    def resizeEvent(self, event: object) -> None:  # type: ignore[override]
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._elide()

    def mouseReleaseEvent(self, event: object) -> None:  # type: ignore[override]
        if self._path:
            QApplication.clipboard().setText(self._path)
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]


class EpisodesPage(ListPage):
    """Episodes as list and detail: choosing a row shows that episode's workspace beside
    the list, in place (`episode_workspace.py`).

    This is the usual three-pane arrangement of mail, notes and issue-tracker apps —
    navigation, list, item — and it keeps one rule: the frame does not change when you
    pick something. A click selects and shows; Enter or a double-click only moves the
    caret into the episode. The list can be hidden for room to write (Ctrl+L), and that
    choice is remembered, because it is the user's and not a mode.
    """

    open_voice = Signal(int)
    open_idea = Signal(int)
    record_requested = Signal()

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__(
            strings.EPISODES_TITLE,
            strings.EPISODE_NEW,
            strings.EPISODE_EMPTY,
            list_weight=2,
            detail_weight=7,
            filter_placeholder=strings.EPISODE_FILTER_PLACEHOLDER,
        )
        self._ws = workspace
        self._events = events
        # (episode_id, note_id, focus) waiting for the list to land on that episode
        self._pending: tuple[int, int | None, bool] | None = None
        # One accent button per screen: here that is the workspace's "New note".
        self.primary.setObjectName("")
        self._seasons: list[Season] = []
        self._season = workspace.settings.season_filter()
        self._build_season_row()

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        self.workspace = EpisodeWorkspacePage(workspace, events)
        col.addWidget(self.workspace)
        self.workspace.episode_saved.connect(self._on_episode_saved)
        self.workspace.episode_gone.connect(lambda: QTimer.singleShot(0, self.refresh))
        self.workspace.delete_requested.connect(self.delete_item)
        self.workspace.list_toggle_requested.connect(self.toggle_list)
        self.workspace.open_voice.connect(self.open_voice)
        self.workspace.open_idea.connect(self.open_idea)
        self.workspace.record_requested.connect(self.record_requested)

        self.list.itemDoubleClicked.connect(lambda _i: self.focus_editor())
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.focus_editor)
        QShortcut(
            QKeySequence("Ctrl+L"),
            self,
            activated=self.toggle_list,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self._list_hidden = False
        self._set_list_hidden(workspace.settings.episode_list_hidden(), remember=False)

    # the list pane ---------------------------------------------------------------------
    def toggle_list(self) -> None:
        self._set_list_hidden(not self._list_hidden)

    def _set_list_hidden(self, hidden: bool, remember: bool = True) -> None:
        had_focus = self.list_side.isAncestorOf(QApplication.focusWidget())
        self._list_hidden = hidden
        self.list_side.setVisible(not hidden)
        self._paint_list_toggle()
        if remember:
            self._ws.settings.set_episode_list_hidden(hidden)
        if hidden and had_focus:
            self.workspace.focus_main()
        elif not hidden and remember:
            self.list.setFocus()

    def _paint_list_toggle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.Text)
        button = self.workspace.list_toggle
        button.setIcon(list_pane_icon(color, self.isRightToLeft(), self._list_hidden))
        button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        button.setToolTip(strings.LIST_SHOW if self._list_hidden else strings.LIST_HIDE)
        self.workspace.more_button.setIcon(more_icon(color))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LayoutDirectionChange):
            self._paint_list_toggle()
        super().changeEvent(event)

    # focus -----------------------------------------------------------------------------
    def focus_main(self) -> None:
        if self._list_hidden:
            self.workspace.focus_main()
        else:
            self.list.setFocus()

    def focus_filter(self) -> None:
        if self._list_hidden:  # asking for the filter is asking for the list
            self._set_list_hidden(False)
        super().focus_filter()

    def focus_editor(self) -> None:
        """Enter or a double-click on a row: carry on writing in that episode."""
        if self.current_id() is not None:
            self.workspace.focus_main()

    def new_shortcut(self) -> None:
        """Ctrl+N means "another one of what I am in": a note inside the episode, an
        episode anywhere else on the page."""
        focus = QApplication.focusWidget()
        if self.workspace.episode_id is not None and self.workspace.isAncestorOf(focus):
            self.workspace.new_note()
        else:
            self.primary_action()

    # seasons ---------------------------------------------------------------------------
    def _build_season_row(self) -> None:
        """Which season the list shows, and the season's own actions beside it."""
        row = QHBoxLayout()
        row.setSpacing(6)
        self.season_box = QComboBox()
        self.season_box.setToolTip(strings.SEASON_FILTER_TOOLTIP)
        self.season_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.season_box.activated.connect(self._on_season_chosen)
        row.addWidget(self.season_box, 1)
        self.season_more = QToolButton(objectName="chromeButton")
        self.season_more.setToolTip(strings.SEASON_ACTIONS_TOOLTIP)
        self.season_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.season_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.season_menu = QMenu(self.season_more)
        self.season_menu.aboutToShow.connect(self._fill_season_menu)
        self.season_more.setMenu(self.season_menu)
        row.addWidget(self.season_more)
        side = self.list_side.layout()
        assert isinstance(side, QVBoxLayout)
        side.insertLayout(2, row)  # under the title and status, over the filter box

    def _fill_seasons(self, episodes: list[Episode] | None = None) -> None:
        """Rebuild the season box: all, each season with its count, then the unfiled."""
        try:
            self._seasons = self._ws.seasons.list_all()
            if episodes is None:
                episodes = self._ws.episodes.list_all()
        except Exception:
            return
        counts: dict[int | None, int] = {}
        for episode in episodes:
            counts[episode.season_id] = counts.get(episode.season_id, 0) + 1
        known = {s.id for s in self._seasons}
        if self._season not in (SEASON_ALL, SEASON_NONE) and int(self._season) not in known:
            self._season = SEASON_ALL  # the season was deleted (or undone) meanwhile
        box = self.season_box
        box.blockSignals(True)
        box.clear()
        box.addItem(strings.SEASON_ALL, SEASON_ALL)
        for season in self._seasons:
            n = local_digits(counts.get(season.id, 0))
            box.addItem(strings.SEASON_ITEM.format(title=season.title, n=n), str(season.id))
        if self._seasons:
            n = local_digits(counts.get(None, 0))
            box.addItem(strings.SEASON_ITEM.format(title=strings.SEASON_NONE, n=n), SEASON_NONE)
        box.setCurrentIndex(max(0, box.findData(self._season)))
        box.blockSignals(False)

    def _fill_season_menu(self) -> None:
        menu = self.season_menu
        menu.clear()
        menu.addAction(strings.SEASON_NEW, self._new_season)
        season = self._current_season()
        if season is not None:
            menu.addSeparator()
            menu.addAction(strings.SEASON_RENAME, lambda: self._rename_season(season))
            menu.addAction(strings.SEASON_DELETE, lambda: self._delete_season(season))

    def _current_season(self) -> Season | None:
        if self._season in (SEASON_ALL, SEASON_NONE):
            return None
        return next((s for s in self._seasons if str(s.id) == self._season), None)

    def _season_id(self) -> int | None:
        """The season a new episode goes into: the one being shown, if any."""
        season = self._current_season()
        return None if season is None else season.id

    def _set_season(self, value: str, remember: bool = True) -> None:
        self._season = value
        if remember:
            self._ws.settings.set_season_filter(value)

    def _on_season_chosen(self, _index: int) -> None:
        self._set_season(str(self.season_box.currentData()))
        self.refresh()

    def show_season(self, season_id: int) -> None:
        """Bring a season into view (after an undo touched it); all of them if it is gone."""
        known = {s.id for s in self._ws.seasons.list_all()}
        self._set_season(str(season_id) if season_id in known else SEASON_ALL)
        self.clear_filter(reload=False)
        self.refresh()

    def _new_season(self) -> None:
        season = create_season(self, self._ws)
        if season is None or season.id is None:
            return
        self._set_season(str(season.id))
        self._events.data_changed.emit()
        self.refresh()

    def _rename_season(self, season: Season) -> None:
        if rename_season(self, self._ws, season):
            self._events.data_changed.emit()
            self._fill_seasons()
            self.update_rows()

    def _delete_season(self, season: Season) -> None:
        if season.id is None:
            return
        if not confirm(self, strings.SEASON_DELETE_CONFIRM.format(title=season.title)):
            return
        try:
            self._ws.seasons.delete(season.id)
        except Exception as exc:
            show_error(self, exc)
            return
        self._set_season(SEASON_ALL)
        self._events.data_changed.emit()
        self.refresh()
        self.workspace.reload()

    def _reveal_episode(self, episode_id: int) -> None:
        """An episode reached from elsewhere must not sit in a season that is not shown."""
        if self._season == SEASON_ALL:
            return
        try:
            episode = self._ws.episodes.get(episode_id)
        except Exception:
            return
        if not self._in_season(episode):
            wanted = SEASON_NONE if episode.season_id is None else str(episode.season_id)
            self._set_season(wanted)

    def _in_season(self, episode: Episode) -> bool:
        if self._season == SEASON_ALL:
            return True
        if self._season == SEASON_NONE:
            return episode.season_id is None
        return str(episode.season_id) == self._season

    def update_rows(self) -> None:
        """Season names changed: redraw the subtitles without reloading the episode."""
        self.refresh(load=False)

    def select(self, item_id: int) -> None:
        self._reveal_episode(item_id)
        super().select(item_id)

    # opening ---------------------------------------------------------------------------
    def open_episode(self, episode_id: int, note_id: int | None = None) -> None:
        """Show an episode from elsewhere in the app (board, tags, search, resume), with
        the caret inside it, ready to write."""
        self.clear_filter(reload=False)
        self._reveal_episode(episode_id)
        self._pending = (episode_id, note_id, True)
        self.refresh(select_id=episode_id)
        self._pending = None

    def _on_episode_saved(self, episode: Episode) -> None:
        self.update_row(self._row(episode))
        self._fill_seasons()  # its season may have changed, and with it the counts

    def _row(self, episode: Episode, tags: dict[int, str] | None = None) -> Row:
        assert episode.id is not None
        subtitle = strings.STATUS_LABELS[episode.status]
        if self._season == SEASON_ALL and episode.season_id is not None:
            # Across all seasons, each row says which one it belongs to.
            season = next((s for s in self._seasons if s.id == episode.season_id), None)
            if season is not None:
                subtitle = season.title + "  ·  " + subtitle
        badge = stale_text(episode)
        if badge:
            subtitle = badge + "  ·  " + subtitle
        if episode.next_action:
            subtitle += "  ·  " + episode.next_action
        names = _tag_labels(self._ws, episode.tag_ids, tags)
        return Row(episode.id, episode.title, subtitle, names)

    def rows(self) -> list[Row]:
        tags = _tag_map(self._ws)
        episodes = self._ws.episodes.list_all()
        self._fill_seasons(episodes)
        self._empty_text = {
            SEASON_ALL: strings.EPISODE_EMPTY,
            SEASON_NONE: strings.SEASON_NONE_EMPTY,
        }.get(self._season, strings.SEASON_EMPTY)
        return [self._row(e, tags) for e in episodes if self._in_season(e)]

    def show_item(self, item_id: int) -> None:
        note_id, focus = None, False
        if self._pending is not None and self._pending[0] == item_id:
            _episode, note_id, focus = self._pending
            self._pending = None
        if self.workspace.episode_id == item_id and note_id is None:
            # The same episode again (the page came back into view, or the list was
            # rebuilt): refresh it where it stands instead of opening it anew.
            self.workspace.reload()
            if focus:
                self.workspace.focus_main()
            return
        self.workspace.open(item_id, note_id, focus=focus)

    def clear_editor(self) -> None:
        self.workspace.clear()

    # navigation state ------------------------------------------------------------------
    def nav_state(self) -> ListPageState:
        extra = {"workspace": self.workspace.nav_state(), "season": self._season}
        return replace(super().nav_state(), extra=extra)

    def restore_nav_state(self, state: object) -> None:
        if isinstance(state, ListPageState):
            self._set_season(str(state.extra.get("season", self._season)))
        super().restore_nav_state(state)
        if isinstance(state, ListPageState):
            self.workspace.restore_nav_state(state.extra.get("workspace"))

    # actions ---------------------------------------------------------------------------
    def primary_action(self) -> None:
        self.clear_filter(reload=False)  # what you just made has to be what you see
        try:
            # Made while a season is shown, it belongs to that season.
            episode = self._ws.episodes.create(
                strings.EPISODE_DEFAULT_TITLE, season_id=self._season_id()
            )
        except Exception as exc:
            show_error(self, exc)
            return
        assert episode.id is not None
        if not self._in_season(episode):  # "no season" was shown
            self._set_season(SEASON_ALL)
        self._events.data_changed.emit()
        self.refresh(select_id=episode.id)
        self.workspace.title_edit.setFocus()
        self.workspace.title_edit.selectAll()

    def delete_item(self, item_id: int) -> None:
        self.workspace.flush()
        try:
            title = self._ws.episodes.get(item_id).title
        except Exception:
            title = ""
        if not confirm(self, strings.EPISODE_DELETE_CONFIRM.format(title=title)):
            return
        try:
            self._ws.episodes.delete(item_id)
        except Exception as exc:
            show_error(self, exc)
        self.workspace.clear()
        self._events.data_changed.emit()
        self.refresh()
        self.focus_main()


class VoicesPage(ListPage):
    TAB_NOTES, TAB_TRANSCRIPT = 0, 1
    settings_requested = Signal()

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
        super().__init__(
            strings.VOICES_TITLE,
            strings.VOICE_IMPORT,
            strings.VOICE_EMPTY,
            filter_placeholder=strings.VOICE_FILTER_PLACEHOLDER,
        )
        self._ws = workspace
        self._events = events
        self._voice: Voice | None = None
        self._pending_note: int | None = None
        self._transcribed: set[int] = set()
        self._note_counts: dict[int, int] = {}
        self.setAcceptDrops(True)
        self.primary.setToolTip("Ctrl+N / Ctrl+O")

        col = QVBoxLayout(self.editor)
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
        install_player_keys(
            self,
            self.player.player,
            (("Insert", self.notes.begin_note), ("Ctrl+Return", self.notes.begin_note)),
        )

    def _row(self, voice: Voice, tags: dict[int, str] | None = None) -> Row:
        assert voice.id is not None
        name = Path(voice.file_path).name
        names = _tag_labels(self._ws, voice.tag_ids, tags)
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
        return Row(voice.id, name, "  ·  ".join(p for p in parts if p), names)

    def rows(self) -> list[Row]:
        self._transcribed = self._ws.transcripts.voice_ids()
        self._note_counts = self._ws.timestamp_notes.counts_by_voice()
        tags = _tag_map(self._ws)
        return [self._row(v, tags) for v in self._ws.voices.list_all()]

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
        self.path.set_path(voice.file_path)
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
        self.clear_filter(reload=False)  # imported files must not land behind a filter box
        self.primary.setEnabled(False)
        self.status.setText(strings.VOICE_IMPORTING)
        run_async(
            lambda: self._ws.voices.import_files(paths),
            self._on_imported,
            self._on_import_failed,
        )

    def _on_imported(self, report: ImportReport) -> None:
        self.primary.setEnabled(True)
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
        # Ideas are short: browsing the list matters more than a very wide editor.
        super().__init__(
            strings.IDEAS_TITLE,
            strings.IDEA_NEW,
            strings.IDEA_EMPTY,
            list_weight=3,
            detail_weight=4,
            filter_placeholder=strings.IDEA_FILTER_PLACEHOLDER,
        )
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

    def _row(self, idea: IdeaNote, tags: dict[int, str] | None = None) -> Row:
        assert idea.id is not None
        names = _tag_labels(self._ws, idea.tag_ids, tags)
        subtitle = format_datetime(idea.updated_at)
        if names:
            subtitle += "  ·  " + strings.LIST_SEPARATOR.join(names)
        return Row(idea.id, _first_line(idea.text), subtitle, names)

    def rows(self) -> list[Row]:
        tags = _tag_map(self._ws)
        return [self._row(i, tags) for i in self._ws.ideas.list_all()]

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
        self.clear_filter()  # an empty draft matches no filter; show it anyway
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
