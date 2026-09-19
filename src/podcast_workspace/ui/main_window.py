"""Main window: sidebar navigation (right, RTL) + global search bar + page stack.

Nav pages: Episodes, Board, Voices, Ideas, Tags (Ctrl+1..5). Off-nav pages: the episode
workspace, the startup resume screen and search results. Alt+← goes back.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.search import SearchHit, SearchKind
from podcast_workspace.services.recording import RecorderNotConfiguredError, launch_recorder
from podcast_workspace.services.settings_service import Theme
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.hotkey import IDEA_HOTKEY, IDEA_HOTKEY_LABEL, GlobalHotkey
from podcast_workspace.ui.idea_inbox import IdeaInbox
from podcast_workspace.ui.pages.board_page import BoardPage
from podcast_workspace.ui.pages.content_pages import EpisodesPage, IdeasPage, VoicesPage
from podcast_workspace.ui.pages.episode_workspace import EpisodeWorkspacePage
from podcast_workspace.ui.pages.resume_page import ResumePage
from podcast_workspace.ui.pages.search_page import SearchPage
from podcast_workspace.ui.pages.tags_page import TagsPage
from podcast_workspace.ui.settings_dialog import SettingsDialog
from podcast_workspace.ui.support import AppEvents, run_async, show_error
from podcast_workspace.ui.theme import ThemeManager, set_native_dark_title_bar

SIDEBAR_WIDTH = 232
SEARCH_DEBOUNCE_MS = 90
WARM_UP_DELAY_MS = 1500
HISTORY_LIMIT = 30
IDEA_HOTKEY_ID = 0xB0B1


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, theme: ThemeManager) -> None:
        super().__init__()
        self._ws = workspace
        self._theme = theme
        self._history: list[QWidget] = []
        self._before_search: QWidget | None = None
        self._first_show = True
        self.events = AppEvents(self)
        self.setWindowTitle(strings.APP_NAME)
        self.setMinimumSize(1100, 680)

        self.player = Player(self)
        self.episodes_page = EpisodesPage(workspace, self.events)
        self.board_page = BoardPage(workspace, self.events)
        self.voices_page = VoicesPage(workspace, self.events, self.player)
        self.ideas_page = IdeasPage(workspace, self.events)
        self.tags_page = TagsPage(workspace, self.events)
        self.workspace_page = EpisodeWorkspacePage(workspace, self.events)
        self.resume_page = ResumePage()
        self.search_page = SearchPage()
        self._pages: list[QWidget] = [
            self.episodes_page,
            self.board_page,
            self.voices_page,
            self.ideas_page,
            self.tags_page,
        ]

        self.search_page.open_hit.connect(self._open_hit)
        self.episodes_page.open_workspace.connect(self.open_episode)
        self.board_page.open_episode.connect(self.open_episode)
        self.workspace_page.back_requested.connect(self.go_back)
        self.workspace_page.open_voice.connect(self.open_voice)
        self.workspace_page.open_idea.connect(self.open_idea)
        self.workspace_page.record_requested.connect(self._record)
        self.resume_page.continue_requested.connect(self.open_episode)
        self.resume_page.skip_requested.connect(lambda: self.navigate(0, focus=True))

        self.inbox = IdeaInbox(workspace)
        self.inbox.saved.connect(self._on_inbox_saved)
        self.hotkey = GlobalHotkey(IDEA_HOTKEY_ID, self)
        self.hotkey.activated.connect(self.inbox.summon)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)  # first widget sits on the right in RTL
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

        self._search_timer = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_search)
        self._warm_timer = QTimer(self, singleShot=True, interval=WARM_UP_DELAY_MS)
        self._warm_timer.timeout.connect(self._warm_up_search)
        self.events.data_changed.connect(self._warm_timer.start)
        self.events.tags_changed.connect(self._warm_timer.start)
        self._warm_timer.start()

        self._install_shortcuts()
        theme.changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme.theme)
        self._start_page()

        geometry = workspace.settings.window_geometry()
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(1320, 840)

    # layout ----------------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        col = QVBoxLayout(sidebar)
        col.setContentsMargins(12, 24, 12, 16)
        col.setSpacing(4)
        title = QLabel(strings.APP_NAME, objectName="appTitle")
        title.setContentsMargins(12, 0, 12, 16)
        col.addWidget(title)
        self.nav = QButtonGroup(self)
        labels = (
            strings.NAV_EPISODES,
            strings.NAV_BOARD,
            strings.NAV_VOICES,
            strings.NAV_IDEAS,
            strings.NAV_TAGS,
        )
        for index, label in enumerate(labels):
            button = QPushButton(label, objectName="navButton")
            button.setCheckable(True)
            button.setToolTip(f"Ctrl+{index + 1}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav.addButton(button, index)
            col.addWidget(button)
        self.nav.idClicked.connect(self.navigate)
        col.addStretch(1)
        settings = QPushButton(strings.SETTINGS, objectName="navButton")
        settings.setToolTip(strings.SETTINGS_TOOLTIP)
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(self.open_settings)
        col.addWidget(settings)
        self.theme_button = QPushButton(objectName="navButton")
        self.theme_button.setToolTip(strings.THEME_TOOLTIP)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._theme.toggle)
        col.addWidget(self.theme_button)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget(objectName="content")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(32, 20, 32, 0)
        self.search = QLineEdit(objectName="searchBar")
        self.search.setPlaceholderText(strings.SEARCH_PLACEHOLDER)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.installEventFilter(self)
        bar.addWidget(self.search)
        col.addLayout(bar)
        self.stack = QStackedWidget()
        for page in (*self._pages, self.workspace_page, self.resume_page, self.search_page):
            self.stack.addWidget(page)
        col.addWidget(self.stack, 1)
        return content

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self._theme.toggle)
        QShortcut(QKeySequence.StandardKey.Quit, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.focus_search)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_back)
        QShortcut(QKeySequence.StandardKey.Back, self, activated=self.go_back)
        for index in range(len(self._pages)):
            QShortcut(
                QKeySequence(f"Ctrl+{index + 1}"),
                self,
                activated=lambda i=index: self.navigate(i, focus=True),
            )
        # F6 cycles focus: sidebar -> search -> page, as in Windows apps.
        QShortcut(QKeySequence("F6"), self, activated=self._cycle_pane_focus)

    def _start_page(self) -> None:
        try:
            info = self._ws.episodes.resume()
        except Exception:
            info = None  # resume is a convenience; never block startup on it
        if info is None:
            self.navigate(0)
            return
        self.resume_page.show_info(info)
        self.show_page(self.resume_page, remember=False)

    # navigation ------------------------------------------------------------------------
    def show_page(self, page: QWidget, focus: bool = False, remember: bool = True) -> None:
        current = self.stack.currentWidget()
        if remember and current is not page and current not in (self.search_page, self.resume_page):
            self._history.append(current)
            del self._history[:-HISTORY_LIMIT]
        self.stack.setCurrentWidget(page)
        index = self._pages.index(page) if page in self._pages else -1
        if index >= 0:
            button = self.nav.button(index)
            if button is not None:
                button.setChecked(True)
        else:
            checked = self.nav.checkedButton()
            if checked is not None:  # no nav item is "current" on off-nav pages
                self.nav.setExclusive(False)
                checked.setChecked(False)
                self.nav.setExclusive(True)
        focus_main = getattr(page, "focus_main", None)
        if focus and callable(focus_main):
            focus_main()

    def navigate(self, index: int, focus: bool = False) -> None:
        self.show_page(self._pages[index], focus=focus)

    def go_back(self) -> None:
        current = self.stack.currentWidget()
        while self._history:
            page = self._history.pop()
            if page is not current:
                self.show_page(page, focus=True, remember=False)
                return
        if current is not self._pages[0]:
            self.show_page(self._pages[0], focus=True, remember=False)

    def open_episode(self, episode_id: int, note_id: int | None = None) -> None:
        self.ideas_page.flush()
        if self.workspace_page.open(episode_id, note_id):
            self.show_page(self.workspace_page)

    def open_voice(self, voice_id: int) -> None:
        self.show_page(self.voices_page)
        self.voices_page.select(voice_id)
        self.voices_page.player.waveform.setFocus()

    def open_idea(self, idea_id: int) -> None:
        self.show_page(self.ideas_page)
        self.ideas_page.select(idea_id)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _leave_search(self) -> None:
        self.search.clear()
        self.show_page(self._before_search or self._pages[0], focus=True, remember=False)

    def _cycle_pane_focus(self) -> None:
        focus = QApplication.focusWidget()
        if focus is not None and self.sidebar.isAncestorOf(focus):
            self.focus_search()
        elif focus is self.search:
            current = self.stack.currentWidget()
            current.setFocus()
            current.focusNextChild()
        else:
            (self.nav.checkedButton() or self.theme_button).setFocus()

    # search ----------------------------------------------------------------------------
    def _run_search(self) -> None:
        query = self.search.text()
        if not query.strip():
            if self.stack.currentWidget() is self.search_page:
                self.show_page(self._before_search or self._pages[0], remember=False)
            return
        try:
            result = self._ws.search.search(query)
        except Exception as exc:
            show_error(self, exc)
            return
        self.search_page.show_result(result)
        if self.stack.currentWidget() is not self.search_page:
            self._before_search = self.stack.currentWidget()
            self.show_page(self.search_page, remember=False)

    def _open_hit(self, hit: SearchHit) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        match hit.kind:
            case SearchKind.EPISODE:
                self.show_page(self.episodes_page, remember=False)
                self.episodes_page.select(hit.source_id)
            case SearchKind.EPISODE_NOTE if hit.owner_id is not None:
                self.open_episode(hit.owner_id, hit.source_id)
            case SearchKind.VOICE:
                self.show_page(self.voices_page, remember=False)
                self.voices_page.select(hit.source_id)
            case SearchKind.TIMESTAMP_NOTE if hit.owner_id is not None:
                self.show_page(self.voices_page, remember=False)
                self.voices_page.open_note(hit.owner_id, hit.source_id)
            case SearchKind.IDEA_NOTE:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.select(hit.source_id)
            case SearchKind.TAG:
                self.show_page(self.tags_page, remember=False)
                self.tags_page.select(hit.source_id)
            case _:
                self.show_page(self._before_search or self._pages[0], remember=False)

    def _warm_up_search(self) -> None:
        run_async(self._ws.search.warm_up, lambda _r: None, lambda _e: None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_Escape:
                self._leave_search()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._search_timer.isActive():
                    self._search_timer.stop()
                    self._run_search()
                if self.stack.currentWidget() is self.search_page:
                    self.search_page.open_current()
                return True
            if event.key() == Qt.Key.Key_Down and self.stack.currentWidget() is self.search_page:
                self.search_page.results.setFocus()
                return True
        return super().eventFilter(watched, event)

    # settings, recorder, inbox ----------------------------------------------------------
    def open_settings(self) -> bool:
        dialog = SettingsDialog(self, self._ws.settings, IDEA_HOTKEY_LABEL, self.hotkey.registered)
        return dialog.exec() == SettingsDialog.DialogCode.Accepted

    def _record(self) -> None:
        path = self._ws.settings.recorder_path()
        if not path and (not self.open_settings() or not self._ws.settings.recorder_path()):
            return
        path = self._ws.settings.recorder_path()
        try:
            launch_recorder(path)
        except RecorderNotConfiguredError:
            self.open_settings()
        except FileNotFoundError:
            QMessageBox.warning(
                self, strings.ERROR_TITLE, strings.RECORDER_MISSING.format(path=path)
            )
        except OSError as exc:
            show_error(self, exc)

    def _on_inbox_saved(self, _idea_id: int) -> None:
        self.events.data_changed.emit()
        if self.stack.currentWidget() is self.ideas_page:
            self.ideas_page.refresh()

    # theme & lifecycle -----------------------------------------------------------------
    def _on_theme_changed(self, theme: Theme) -> None:
        dark = theme is Theme.DARK
        self.theme_button.setText(strings.THEME_TO_LIGHT if dark else strings.THEME_TO_DARK)
        set_native_dark_title_bar(self, dark)
        set_native_dark_title_bar(self.inbox, dark)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        set_native_dark_title_bar(self, self._theme.theme is Theme.DARK)
        if self._first_show:
            self._first_show = False
            self.hotkey.register(int(self.winId()), *IDEA_HOTKEY)
            if self.stack.currentWidget() is self.resume_page:
                QTimer.singleShot(0, self.resume_page.focus_main)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ideas_page.flush()  # pending autosaves must not be lost
        self.workspace_page.flush()
        self._ws.settings.set_window_geometry(bytes(self.saveGeometry().data()))
        self.hotkey.unregister()
        self.inbox.close()
        self.player.shutdown()
        super().closeEvent(event)
