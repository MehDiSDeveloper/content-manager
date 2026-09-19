"""Main window: sidebar navigation (right, RTL) + global search bar + page stack."""

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
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.search import SearchHit, SearchKind
from podcast_workspace.services.settings_service import Theme
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.pages.content_pages import EpisodesPage, IdeasPage, VoicesPage
from podcast_workspace.ui.pages.search_page import SearchPage
from podcast_workspace.ui.pages.tags_page import TagsPage
from podcast_workspace.ui.support import AppEvents, run_async, show_error
from podcast_workspace.ui.theme import ThemeManager, set_native_dark_title_bar

SIDEBAR_WIDTH = 232
SEARCH_DEBOUNCE_MS = 90
WARM_UP_DELAY_MS = 1500


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, theme: ThemeManager) -> None:
        super().__init__()
        self._ws = workspace
        self._theme = theme
        self._last_page = 0
        self.events = AppEvents(self)
        self.setWindowTitle(strings.APP_NAME)
        self.setMinimumSize(1000, 640)

        self.episodes_page = EpisodesPage(workspace, self.events)
        self.player = Player(self)
        self.voices_page = VoicesPage(workspace, self.events, self.player)
        self.ideas_page = IdeasPage(workspace, self.events)
        self.tags_page = TagsPage(workspace, self.events)
        self.search_page = SearchPage()
        self.search_page.open_hit.connect(self._open_hit)
        self._pages: list[EpisodesPage | VoicesPage | IdeasPage | TagsPage] = [
            self.episodes_page,
            self.voices_page,
            self.ideas_page,
            self.tags_page,
        ]

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
        self.navigate(0)

        geometry = workspace.settings.window_geometry()
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(1280, 800)

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
        labels = (strings.NAV_EPISODES, strings.NAV_VOICES, strings.NAV_IDEAS, strings.NAV_TAGS)
        for index, label in enumerate(labels):
            button = QPushButton(label, objectName="navButton")
            button.setCheckable(True)
            button.setToolTip(f"Ctrl+{index + 1}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav.addButton(button, index)
            col.addWidget(button)
        self.nav.idClicked.connect(self.navigate)
        col.addStretch(1)
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
        for page in (*self._pages, self.search_page):
            self.stack.addWidget(page)
        col.addWidget(self.stack, 1)
        return content

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self._theme.toggle)
        QShortcut(QKeySequence.StandardKey.Quit, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.focus_search)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)
        for index in range(len(self._pages)):
            QShortcut(
                QKeySequence(f"Ctrl+{index + 1}"),
                self,
                activated=lambda i=index: self.navigate(i, focus=True),
            )
        # F6 cycles focus: sidebar -> search -> page, as in Windows apps.
        QShortcut(QKeySequence("F6"), self, activated=self._cycle_pane_focus)

    # navigation ------------------------------------------------------------------------
    def navigate(self, index: int, focus: bool = False) -> None:
        self._last_page = index
        button = self.nav.button(index)
        if button is not None:
            button.setChecked(True)
        page = self._pages[index]
        self.stack.setCurrentWidget(page)
        if focus:
            page.focus_main()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _leave_search(self) -> None:
        self.search.clear()
        self.navigate(self._last_page, focus=True)

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
                self.navigate(self._last_page)
            return
        try:
            result = self._ws.search.search(query)
        except Exception as exc:
            show_error(self, exc)
            return
        self.search_page.show_result(result)
        if self.stack.currentWidget() is not self.search_page:
            self.stack.setCurrentWidget(self.search_page)
            checked = self.nav.checkedButton()
            if checked is not None:  # no nav item is "current" while showing results
                self.nav.setExclusive(False)
                checked.setChecked(False)
                self.nav.setExclusive(True)

    def _open_hit(self, hit: SearchHit) -> None:
        targets: dict[SearchKind, tuple[int, int | None]] = {
            SearchKind.EPISODE: (0, hit.source_id),
            SearchKind.EPISODE_NOTE: (0, hit.owner_id),
            SearchKind.VOICE: (1, hit.source_id),
            SearchKind.TIMESTAMP_NOTE: (1, hit.owner_id),
            SearchKind.IDEA_NOTE: (2, hit.source_id),
            SearchKind.TAG: (3, hit.source_id),
        }
        index, item_id = targets[hit.kind]
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.navigate(index)
        if hit.kind is SearchKind.TIMESTAMP_NOTE and item_id is not None:
            self.voices_page.open_note(item_id, hit.source_id)
        elif item_id is not None:
            self._pages[index].select(item_id)

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

    # theme & lifecycle -----------------------------------------------------------------
    def _on_theme_changed(self, theme: Theme) -> None:
        dark = theme is Theme.DARK
        self.theme_button.setText(strings.THEME_TO_LIGHT if dark else strings.THEME_TO_DARK)
        set_native_dark_title_bar(self, dark)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        set_native_dark_title_bar(self, self._theme.theme is Theme.DARK)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ideas_page.flush()  # a pending idea autosave must not be lost
        self._ws.settings.set_window_geometry(bytes(self.saveGeometry().data()))
        self.player.shutdown()
        super().closeEvent(event)
