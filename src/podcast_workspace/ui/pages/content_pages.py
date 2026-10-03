"""The Episodes page, and the pieces its sibling list pages share (`ideas_page.py`)."""

from collections.abc import Hashable, Iterable
from dataclasses import replace

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.entities import Episode, Season, in_order
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.icons import NAV_ICON_SIZE, list_pane_icon, more_icon
from podcast_workspace.ui.pages.base import ListPage, ListPageState, Row
from podcast_workspace.ui.pages.episode_workspace import EpisodeWorkspacePage, stale_text
from podcast_workspace.ui.pages.season_brief import SeasonBriefPage, SeasonCard
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs
from podcast_workspace.ui.seasons import create_season, rename_season
from podcast_workspace.ui.support import (
    AppEvents,
    confirm,
    local_digits,
    numbered,
    show_error,
)

AUTOSAVE_DELAY_MS = 700
SEASON_ALL, SEASON_NONE = "all", "none"  # the season box's two fixed entries
MINI_LIST_HEIGHT = 208


def danger_button(text: str) -> QPushButton:
    return QPushButton(text, objectName="danger")


def first_line(text: str, width: int = 70) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


def tag_map(workspace: Workspace) -> dict[int, str]:
    """id -> name for every tag, read once per list rebuild instead of once per row."""
    return {t.id: t.name for t in workspace.tags.list_all() if t.id is not None}


def tag_labels(
    workspace: Workspace, tag_ids: Iterable[int], known: dict[int, str] | None = None
) -> tuple[str, ...]:
    """The names a row carries, for the filter box and the subtitle. `known` is the map
    from `tag_map`; without one this falls back to the service (a single row redrawn
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

    A season on show has a brief (`season_brief.py`): its card over the list opens it in
    the detail pane, with no episode selected, until an episode is chosen again.
    """

    open_voice = Signal(int)
    open_idea = Signal(int)
    record_requested = Signal()
    settings_requested = Signal()  # transcription settings, from a previewed voice

    def __init__(
        self, workspace: Workspace, events: AppEvents, player: Player, jobs: TranscriptionJobs
    ) -> None:
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
        self._brief_open = False
        self._build_season_row()

        col = QVBoxLayout(self.editor)
        col.setContentsMargins(0, 0, 0, 0)
        self.editor_stack = QStackedWidget()
        col.addWidget(self.editor_stack)
        self.workspace = EpisodeWorkspacePage(workspace, events, player, jobs)
        self.editor_stack.addWidget(self.workspace)
        self.brief = SeasonBriefPage(workspace, events)
        self.brief.saved.connect(self._on_brief_saved)
        self.brief.list_toggle_requested.connect(self.toggle_list)
        self.editor_stack.addWidget(self.brief)
        self.workspace.episode_saved.connect(self._on_episode_saved)
        self.workspace.number_saved.connect(lambda: self.refresh(load=False))
        self.workspace.episode_gone.connect(lambda: QTimer.singleShot(0, self.refresh))
        self.workspace.delete_requested.connect(self.delete_item)
        self.workspace.list_toggle_requested.connect(self.toggle_list)
        self.workspace.open_voice.connect(self.open_voice)
        self.workspace.open_idea.connect(self.open_idea)
        self.workspace.record_requested.connect(self.record_requested)
        self.workspace.settings_requested.connect(self.settings_requested)

        self.list.itemDoubleClicked.connect(lambda _i: self.focus_editor())
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.focus_editor)
        QShortcut(
            QKeySequence("Ctrl+L"),
            self,
            activated=self.toggle_list,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        QShortcut(
            QKeySequence("Ctrl+P"),
            self,
            activated=self._open_script_prompt,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self._list_hidden = False
        self._set_list_hidden(workspace.settings.episode_list_hidden(), remember=False)

    def _open_script_prompt(self) -> None:
        # Only for the episode on show: with the season brief open, there is none.
        if self.editor_stack.currentWidget() is self.workspace:
            self.workspace.open_script_prompt()

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
            self._detail_focus()
        elif not hidden and remember:
            self.list.setFocus()

    def _paint_list_toggle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.Text)
        for button in (self.workspace.list_toggle, self.brief.list_toggle):
            button.setIcon(list_pane_icon(color, self.isRightToLeft(), self._list_hidden))
            button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            button.setToolTip(strings.LIST_SHOW if self._list_hidden else strings.LIST_HIDE)
        self.workspace.more_button.setIcon(more_icon(color))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LayoutDirectionChange):
            self._paint_list_toggle()
        super().changeEvent(event)

    # focus -----------------------------------------------------------------------------
    def _detail_focus(self) -> None:
        if self._brief_open:
            self.brief.focus_main()
        else:
            self.workspace.focus_main()

    def focus_main(self) -> None:
        if self._list_hidden:
            self._detail_focus()
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
        elif self._brief_open:
            self.brief.focus_main()

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
        self.season_card = SeasonCard()
        self.season_card.clicked.connect(self.open_brief)
        self.season_card.hide()
        side.insertWidget(3, self.season_card)

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
            title = numbered(season.title, season.number)
            box.addItem(strings.SEASON_ITEM.format(title=title, n=n), str(season.id))
        if self._seasons:
            n = local_digits(counts.get(None, 0))
            box.addItem(strings.SEASON_ITEM.format(title=strings.SEASON_NONE, n=n), SEASON_NONE)
        box.setCurrentIndex(max(0, box.findData(self._season)))
        box.blockSignals(False)
        season = self._current_season()
        self.season_card.setVisible(season is not None)
        if season is not None:
            self.season_card.set_summary(season.readme)

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
        """Bring a season and its brief into view (after an undo touched it); all of
        them if it is gone."""
        known = {s.id for s in self._ws.seasons.list_all()}
        self._set_season(str(season_id) if season_id in known else SEASON_ALL)
        if season_id in known:
            self._enter_brief()
        self.clear_filter(reload=False)
        self.refresh()

    # the season's brief ------------------------------------------------------------------
    def open_brief(self) -> None:
        """The card was clicked: the season on show takes the detail pane."""
        if self._current_season() is None:
            return
        self._enter_brief()
        self.refresh()

    def _enter_brief(self) -> None:
        if not self._brief_open:
            self.workspace.clear()  # saves what it was holding
            self._brief_open = True

    def _leave_brief(self) -> None:
        if self._brief_open:
            self.brief.clear()
            self._brief_open = False
        self.editor_stack.setCurrentWidget(self.workspace)
        self.season_card.setChecked(False)

    def _show_brief(self, season: Season) -> None:
        """The list stays as it is, with no row chosen: the brief is what is shown."""
        assert season.id is not None
        self.list.blockSignals(True)
        self.list.setCurrentItem(None)
        self.list.clearSelection()
        self.list.blockSignals(False)
        self.detail.setCurrentIndex(1)
        self.editor_stack.setCurrentWidget(self.brief)
        self.season_card.setChecked(True)
        self.brief.open(season.id)

    def _on_brief_saved(self, season: Season) -> None:
        renamed = any(
            s.id == season.id and (s.title, s.number) != (season.title, season.number)
            for s in self._seasons
        )
        self._seasons = [season if s.id == season.id else s for s in self._seasons]
        if renamed:
            self._fill_seasons()  # the box names and orders it
        else:
            self.season_card.set_summary(season.readme)

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
        self.brief.flush()
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

    def refresh(self, select_id: Hashable | None = None, load: bool = True) -> None:
        """While the brief is open, the list is rebuilt beside it and nothing in it is
        chosen. Going to an episode (`select_id`), or leaving the season, closes it."""
        if not self._brief_open or select_id is not None:
            self._leave_brief()
            super().refresh(select_id, load)
            return
        self.brief.flush()  # the list reads the season's brief for its card
        super().refresh(load=False)
        season = self._current_season()
        if season is None:  # the season was left, deleted or undone meanwhile
            self._leave_brief()
            super().refresh(load=load)
            return
        self._show_brief(season)

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
                subtitle = numbered(season.title, season.number) + "  ·  " + subtitle
        badge = stale_text(episode)
        if badge:
            subtitle = badge + "  ·  " + subtitle
        if episode.next_action:
            subtitle += "  ·  " + episode.next_action
        names = tag_labels(self._ws, episode.tag_ids, tags)
        return Row(episode.id, numbered(episode.title, episode.number), subtitle, names)

    def rows(self) -> list[Row]:
        tags = tag_map(self._ws)
        episodes = self._ws.episodes.list_all()
        self._fill_seasons(episodes)
        self._empty_text = {
            SEASON_ALL: strings.EPISODE_EMPTY,
            SEASON_NONE: strings.SEASON_NONE_EMPTY,
        }.get(self._season, strings.SEASON_EMPTY)
        shown = [e for e in episodes if self._in_season(e)]
        if self._current_season() is not None:
            shown = in_order(shown)  # one season reads as a run: in its order
        return [self._row(e, tags) for e in shown]

    def show_item(self, item_id: int) -> None:
        self._leave_brief()  # an episode was chosen in the list
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
        extra = {
            "workspace": self.workspace.nav_state(),
            "season": self._season,
            "brief": self._brief_open,
        }
        return replace(super().nav_state(), extra=extra)

    def restore_nav_state(self, state: object) -> None:
        if isinstance(state, ListPageState):
            self._set_season(str(state.extra.get("season", self._season)))
            if state.extra.get("brief"):
                self._enter_brief()
            else:
                self._leave_brief()
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
