"""Main window: sidebar (right in RTL, left in LTR) holding search + navigation, and the
page stack.

Nav pages: Episodes, Board, Ideas (audio and text), Audio folder, Tags, Trash (Ctrl+1..6).
Off-nav page: search results. An episode is always shown in one place — the Episodes
page, beside its list — whether it is reached from there, the board, a tag, a search hit
or the «pick up where you left off» toast the app opens with.

The sidebar folds down to a rail of icons (Ctrl+B) when the page needs the width, and
remembers that it did.

Going back (Alt+←, the sidebar's Back button, and the episode workspace's own) walks the
trail in `ui/navigation.py`, which carries each page's state as well as its identity, so
returning lands on the row and the filter the user left rather than on a page that has
reset itself. The Back button names where it goes, because a control that only says
"back" asks the user to remember what the app already knows.

Also owns the app-wide background pieces: Bale bot, transcription jobs, settings dialog.
"""

from datetime import UTC, datetime

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPalette,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.audio.engine import Player
from podcast_workspace.domain.bot_input import shorten
from podcast_workspace.domain.lifecycle import TRASH_DAYS, ArchiveScope
from podcast_workspace.domain.search import SearchHit, SearchKind
from podcast_workspace.services.bale_bot import BotStatus, ItemKind, ItemRef
from podcast_workspace.services.history import Change, ChangeKind, Target, TargetKind
from podcast_workspace.services.recording import RecorderNotConfiguredError, launch_recorder
from podcast_workspace.services.settings_service import Theme
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.bot_controller import BotController
from podcast_workspace.ui.hotkey import IDEA_HOTKEY, IDEA_HOTKEY_LABEL, GlobalHotkey
from podcast_workspace.ui.icons import (
    NAV_ICON_SIZE,
    back_icon,
    board_icon,
    episodes_icon,
    folder_icon,
    history_icon,
    ideas_icon,
    search_icon,
    settings_icon,
    sidebar_icon,
    tags_icon,
    theme_icon,
    trash_icon,
    voices_icon,
)
from podcast_workspace.ui.idea_inbox import IdeaInbox
from podcast_workspace.ui.navigation import NavEntry, NavigationHistory, capture_state
from podcast_workspace.ui.pages.board_page import BoardPage
from podcast_workspace.ui.pages.content_pages import EpisodesPage
from podcast_workspace.ui.pages.ideas_page import IdeasPage
from podcast_workspace.ui.pages.search_page import SearchPage
from podcast_workspace.ui.pages.source_page import SourcePage
from podcast_workspace.ui.pages.tags_page import TagsPage
from podcast_workspace.ui.pages.trash_page import TrashPage
from podcast_workspace.ui.player.transcript_panel import TranscriptionJobs
from podcast_workspace.ui.settings_dialog import (
    TAB_DATA,
    TAB_GENERAL,
    TAB_TRANSCRIPTION,
    SettingsDialog,
)
from podcast_workspace.ui.support import (
    AppEvents,
    describe_change,
    local_digits,
    run_async,
    show_error,
)
from podcast_workspace.ui.theme import (
    TEXT_WEIGHT,
    ThemeManager,
    colors,
    section_ink,
    set_native_dark_title_bar,
)
from podcast_workspace.ui.toast import Toast
from podcast_workspace.ui.widgets.key_hint import KeyHint, attach_key_hint

SIDEBAR_WIDTH = 240
SIDEBAR_COMPACT_WIDTH = 68
NAV_TILE_SIZE = 30
SEARCH_DEBOUNCE_MS = 90
WARM_UP_DELAY_MS = 1500
COUNTS_DELAY_MS = 250
BACKUP_CHECK_DELAY_MS = 1200  # after the window has settled, not in the way of startup
PURGE_INTERVAL_MS = 60 * 60 * 1000  # the 30-day trash is emptied hourly while the app is open
IDEA_HOTKEY_ID = 0xB0B1
START_PAGE = 2  # Ideas: the app opens where new ideas land
RESUME_SHOW_MS = 20_000  # the startup «continue» toast: longer than news, not for ever
RESUME_TITLE_CHARS = 60
# Changes worth a toast: the ones that take something away, where noticing late is the
# whole problem. Everything else is visible on the page as it happens.
UNDO_OFFERED = frozenset(
    {
        ChangeKind.DELETE,
        ChangeKind.TAGS_REMOVED,
        ChangeKind.UNLINKED,
        ChangeKind.MERGE,
        ChangeKind.ARCHIVE,
        ChangeKind.TRASH,
    }
)


class NavButton(QPushButton):
    """Sidebar entry: icon, label, and on the far edge the section's item count and the
    keycap of its shortcut.

    The parts are child labels in a layout rather than the button's own text and icon,
    so RTL puts them in reading order and the count lands against the far edge. Mouse
    events pass through the children, keeping the whole row clickable.
    """

    def __init__(self, label: str, index: int, section: str = "", keys: str = "") -> None:
        super().__init__(objectName="navButton")
        self.index = index
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 12, 4)
        row.setSpacing(10)
        # The icon sits on a small tile in its section's pastel (theme.SECTION_INKS).
        self.glyph = QLabel(objectName="navGlyph")
        self.glyph.setProperty("section", section)
        self.glyph.setFixedSize(NAV_TILE_SIZE, NAV_TILE_SIZE)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.glyph)
        self.label = QLabel(label)
        row.addWidget(self.label)
        row.addStretch(1)
        self.count = QLabel(objectName="muted")
        count_font = self.count.font()
        count_font.setPointSizeF(max(7.5, count_font.pointSizeF() - 1.5))
        self.count.setFont(count_font)
        row.addWidget(self.count)
        self.keys = KeyHint(keys)
        self.keys.setVisible(bool(keys))
        row.addWidget(self.keys)
        for child in (self.glyph, self.label, self.count):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._restyle)
        self._restyle(False)

    def sizeHint(self) -> QSize:
        # A button with no text of its own would otherwise collapse: its size is the
        # layout's. Width is the rail's to decide, so a long label asks for no more
        # than a short one does.
        hint = self.layout().totalSizeHint()
        return QSize(0, hint.height()) if getattr(self, "_label_text", "") else hint

    def minimumSizeHint(self) -> QSize:
        minimum = self.layout().totalMinimumSize()
        return QSize(0, minimum.height()) if getattr(self, "_label_text", "") else minimum

    def set_icon(self, icon: QIcon) -> None:
        self.glyph.setPixmap(icon.pixmap(NAV_ICON_SIZE, NAV_ICON_SIZE))

    def set_compact(self, compact: bool) -> None:
        """Icon only, centred on the rail; the label moves into the tooltip."""
        self.label.setVisible(not compact)
        self.count.setVisible(not compact)
        self.keys.setVisible(not compact and bool(self.keys.text()))
        # Folded, equal margins centre the glyph tile on the rail.
        self.layout().setContentsMargins(*((9, 4, 9, 4) if compact else (6, 4, 12, 4)))

    def set_count(self, count: int | None) -> None:
        self.count.setText("" if count is None else local_digits(count))

    def set_label(self, text: str) -> None:
        """Replace the label, elided to whatever room the rail leaves for it."""
        self._label_text = text
        self._elide_label()

    def _elide_label(self) -> None:
        text = getattr(self, "_label_text", "")
        if not text:
            return
        row = self.layout()
        margins = row.contentsMargins()
        taken = margins.left() + margins.right() + row.spacing() + self.glyph.width()
        if self.keys.isVisibleTo(self):
            taken += row.spacing() + self.keys.sizeHint().width()
        room = max(40, self.width() - taken - 4)
        self.label.setText(
            self.label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, room)
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide_label()

    def _restyle(self, checked: bool) -> None:
        """QSS cannot reach the child labels; mirror the checked look by hand."""
        font = self.label.font()
        font.setWeight(QFont.Weight.DemiBold if checked else TEXT_WEIGHT)
        self.label.setFont(font)
        role = QPalette.ColorRole.Link if checked else QPalette.ColorRole.PlaceholderText
        self.count.setStyleSheet(f"color: {self.palette().color(role).name()};")


class TextEditorKeys(QObject):
    """Rides on the focused text widget and decides who owns Ctrl+Z / Ctrl+Y.

    Qt lets a focused editor claim those keys before any window shortcut, and it claims
    them even with an empty undo stack — which would leave the app's own history
    unreachable from anywhere text can be typed. Swallowing the editor's claim, and only
    when it has nothing of its own to take back, gives both their turn: the editor
    unwinds your typing first, then the same key starts stepping through the workspace.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.target: QWidget | None = None

    def attach(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        self.target = widget

    def detach(self) -> None:
        target, self.target = self.target, None
        try:
            if target is not None:
                target.removeEventFilter(self)
        except RuntimeError:
            pass  # the widget was destroyed while it had focus

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.target and event.type() == QEvent.Type.ShortcutOverride:
            assert isinstance(event, QKeyEvent)
            if self._takes_over(event):
                return True  # unclaimed: the window shortcut fires instead
        return super().eventFilter(watched, event)

    def _takes_over(self, event: QKeyEvent) -> bool:
        if event.matches(QKeySequence.StandardKey.Undo):
            return not self._editor_has(redo=False)
        redo = event.matches(QKeySequence.StandardKey.Redo) or (
            event.key() == Qt.Key.Key_Z
            and event.modifiers()
            == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        )
        return redo and not self._editor_has(redo=True)

    def _editor_has(self, redo: bool) -> bool:
        widget = self.target
        if isinstance(widget, QLineEdit):
            return widget.isRedoAvailable() if redo else widget.isUndoAvailable()
        if isinstance(widget, QPlainTextEdit | QTextEdit):
            document = widget.document()
            return document.isRedoAvailable() if redo else document.isUndoAvailable()
        return False


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, theme: ThemeManager) -> None:
        super().__init__()
        self._ws = workspace
        self._theme = theme
        self._history = NavigationHistory()
        self._before_search: NavEntry | None = None
        self._first_show = True
        self._compact = workspace.settings.sidebar_compact()
        self._bot_active = False
        self.restart_requested = False  # read by app.main() once the window has closed
        self.events = AppEvents(self)
        self.setWindowTitle(strings.APP_NAME)
        self.setMinimumSize(1100, 680)

        self.player = Player(self)
        self.player.restore_keep_pause(workspace.settings.silence_keep_ms())
        self.player.keep_pause_settled.connect(workspace.settings.set_silence_keep_ms)
        self.player.restore_volume(workspace.settings.player_volume())
        self.player.volume_settled.connect(workspace.settings.set_player_volume)
        self.transcription_jobs = TranscriptionJobs(workspace, self)
        self.bot = BotController(workspace.bot, self)
        self._settings_dialog: SettingsDialog | None = None
        self.episodes_page = EpisodesPage(
            workspace, self.events, self.player, self.transcription_jobs
        )
        self.board_page = BoardPage(workspace, self.events)
        self.ideas_page = IdeasPage(workspace, self.events, self.player, self.transcription_jobs)
        self.source_page = SourcePage(workspace, self.events, self.player)
        self.tags_page = TagsPage(workspace, self.events)
        self.trash_page = TrashPage(workspace, self.events)
        self.workspace_page = self.episodes_page.workspace  # lives inside the Episodes page
        self.search_page = SearchPage()
        self._pages: list[QWidget] = [
            self.episodes_page,
            self.board_page,
            self.ideas_page,
            self.source_page,
            self.tags_page,
            self.trash_page,
        ]

        self.search_page.open_hit.connect(self._open_hit)
        self.search_page.scope_changed.connect(self._run_search)
        self.episodes_page.open_voice.connect(self.open_voice)
        self.episodes_page.open_idea.connect(self.open_idea)
        self.episodes_page.record_requested.connect(self._record)
        self.episodes_page.settings_requested.connect(lambda: self.open_settings(TAB_TRANSCRIPTION))
        self.board_page.open_episode.connect(self.open_episode)
        self.tags_page.open_episode.connect(lambda i: self.open_episode(i, None))
        self.tags_page.open_voice.connect(self.open_voice)
        self.tags_page.open_idea.connect(self.open_idea)
        self.source_page.open_voice.connect(self.open_voice)
        self.source_page.record_requested.connect(self._record)
        self.ideas_page.settings_requested.connect(lambda: self.open_settings(TAB_TRANSCRIPTION))
        self.ideas_page.open_episode.connect(lambda i: self.open_episode(i, None))
        self.ideas_page.new_episode.connect(self.open_new_episode)
        self.bot.status_changed.connect(self._on_bot_status)
        self.transcription_jobs.queue_changed.connect(self._show_transcribe_progress)
        self.transcription_jobs.progress.connect(lambda *_: self._show_transcribe_progress())
        self.bot.item_received.connect(self._on_bot_item)

        self.inbox = IdeaInbox(workspace)
        self.inbox.saved.connect(self._on_inbox_saved)
        self.hotkey = GlobalHotkey(IDEA_HOTKEY_ID, self)
        self.hotkey.activated.connect(self.inbox.summon)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)  # first widget: on the right in RTL, left in LTR
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

        self._search_timer = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_search)
        self._warm_timer = QTimer(self, singleShot=True, interval=WARM_UP_DELAY_MS)
        self._warm_timer.timeout.connect(self._warm_up_search)
        self._counts_timer = QTimer(self, singleShot=True, interval=COUNTS_DELAY_MS)
        self._counts_timer.timeout.connect(self._refresh_counts)
        self.events.data_changed.connect(self._warm_timer.start)
        self.events.tags_changed.connect(self._warm_timer.start)
        self.events.data_changed.connect(self._counts_timer.start)
        self.source_page.pending_changed.connect(self._counts_timer.start)
        self.events.tags_changed.connect(self._counts_timer.start)
        self.events.data_changed.connect(self._on_history_touched)
        self.events.tags_changed.connect(self._on_history_touched)
        self._last_change: Change | None = None
        self._sync_history()
        # Ctrl+Z belongs to a focused text editor while it has edits of its own; the
        # filter hands the key to the app history the moment it does not.
        self._key_filter = TextEditorKeys(self)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._watch_for_history_keys)
        self._warm_timer.start()
        # Items 30 days in the trash go before anything is counted or shown.
        self._auto_purged = self._purge_trash()
        self._purge_timer = QTimer(self, interval=PURGE_INTERVAL_MS)
        self._purge_timer.timeout.connect(self._on_purge_timer)
        self._purge_timer.start()
        self._refresh_counts()

        self._install_shortcuts()
        self._apply_compact()
        theme.changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme.theme)
        self._start_page()

        geometry = workspace.settings.window_geometry()
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(1320, 840)

    # layout ----------------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        """Right-hand rail (RTL): title, search, navigation, then the app's own controls.

        Search lives here rather than over the page so every page starts with its own
        title, and so searching and navigating sit together.
        """
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        col = QVBoxLayout(sidebar)
        col.setContentsMargins(12, 20, 12, 14)
        col.setSpacing(4)
        brand = self._brand_row = QHBoxLayout()
        brand.setContentsMargins(8, 0, 8, 14)
        brand.setSpacing(10)
        self.app_mark = QLabel(objectName="appMark")
        self.app_mark.setFixedSize(34, 34)
        self.app_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(self.app_mark)
        self.app_title = QLabel(strings.APP_NAME, objectName="appTitle")
        brand.addWidget(self.app_title, 1)
        col.addLayout(brand)

        self.search = QLineEdit(objectName="sidebarSearch")
        self.search.setPlaceholderText(strings.SEARCH_PLACEHOLDER)
        self.search.setToolTip(strings.SEARCH_TOOLTIP)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.installEventFilter(self)
        self._search_action = self.search.addAction(
            search_icon(self.palette().color(QPalette.ColorRole.PlaceholderText)),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        attach_key_hint(self.search, "Ctrl+K")
        col.addWidget(self.search)
        # Folded, search is a button that unfolds the rail and puts the caret in the box.
        self.search_button = QToolButton(objectName="chromeButton")
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.search_button.setToolTip(strings.SEARCH_TOOLTIP)
        self.search_button.clicked.connect(self.focus_search)
        col.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addSpacing(8)

        # Back sits with the other ways of moving, above the destinations it competes
        # with. It stays in place when there is nowhere to go (disabled, like undo)
        # rather than appearing and disappearing under the user's pointer.
        self.back_button = NavButton(strings.NAV_BACK, -1, keys="Alt+←")
        self.back_button.setCheckable(False)
        self.back_button.clicked.connect(self.go_back)
        col.addWidget(self.back_button)
        col.addSpacing(10)

        self.nav = QButtonGroup(self)
        self.nav_buttons: list[NavButton] = []
        entries = (
            (strings.NAV_EPISODES, episodes_icon, "episodes"),
            (strings.NAV_BOARD, board_icon, "board"),
            (strings.NAV_IDEAS, ideas_icon, "ideas"),
            (strings.NAV_SOURCE, folder_icon, "source"),
            (strings.NAV_TAGS, tags_icon, "tags"),
            (strings.NAV_TRASH, trash_icon, "trash"),
        )
        for index, (label, _painter, section) in enumerate(entries):
            button = NavButton(label, index, section, keys=f"Ctrl+{index + 1}")
            button.setToolTip(strings.NAV_TOOLTIP.format(label=label, keys=f"Ctrl+{index + 1}"))
            self.nav.addButton(button, index)
            self.nav_buttons.append(button)
            col.addWidget(button)
        self._nav_painters = [(painter, section) for _label, painter, section in entries]
        self.nav.idClicked.connect(self.navigate)
        col.addStretch(1)

        # Undo lives with the app's own controls, in reach from every page, and names
        # the change it would take back in its tooltip.
        # Undo on the left and redo on the right in every language, like their arrows.
        history = self._history_row = QBoxLayout(self._history_direction())
        history.setSpacing(4)
        self.undo_button = NavButton(strings.UNDO, -1, keys="Ctrl+Z")
        self.undo_button.setCheckable(False)
        self.undo_button.setProperty("framed", True)
        self.undo_button.clicked.connect(self.undo)
        history.addWidget(self.undo_button, 1)
        self.redo_button = QToolButton(objectName="chromeButton")
        self.redo_button.setProperty("framed", True)
        self.redo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.redo_button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.redo_button.clicked.connect(self.redo)
        history.addWidget(self.redo_button)
        col.addLayout(history)
        col.addSpacing(6)

        self.bot_label = QLabel(objectName="muted")
        self.bot_label.setContentsMargins(12, 0, 12, 6)
        self.bot_label.setWordWrap(True)
        self.bot_label.hide()
        col.addWidget(self.bot_label)
        # «Transcribe all» runs for a long time, so its progress shows from every page.
        self.transcribe_label = QLabel(objectName="muted")
        self.transcribe_label.setContentsMargins(12, 0, 12, 6)
        self.transcribe_label.setWordWrap(True)
        self.transcribe_label.hide()
        col.addWidget(self.transcribe_label)
        divider = QFrame(objectName="divider")
        col.addWidget(divider)
        col.addSpacing(6)

        footer = self._footer_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        footer.setSpacing(4)
        self.settings_button = NavButton(strings.SETTINGS, -1)
        self.settings_button.setCheckable(False)
        self.settings_button.setToolTip(strings.SETTINGS_TOOLTIP)
        self.settings_button.clicked.connect(lambda: self.open_settings())
        footer.addWidget(self.settings_button, 1)
        self.theme_button = QToolButton(objectName="chromeButton")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.theme_button.clicked.connect(self._theme.toggle)
        footer.addWidget(self.theme_button)
        # Folding sits with the app's own controls, and stays on the rail when folded:
        # it is the one thing that must remain in reach to unfold it again.
        self.fold_button = QToolButton(objectName="chromeButton")
        self.fold_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fold_button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.fold_button.clicked.connect(self.toggle_sidebar)
        footer.addWidget(self.fold_button)
        col.addLayout(footer)
        return sidebar

    def toggle_sidebar(self) -> None:
        self._compact = not self._compact
        self._ws.settings.set_sidebar_compact(self._compact)
        self._apply_compact()

    def _apply_compact(self) -> None:
        """Fold the sidebar to a rail of icons, or open it out again.

        Folded, every destination keeps its place and its icon (and says its name in a
        tooltip), so the rail is the same map at a smaller size, not a different one.
        """
        compact = self._compact
        self.sidebar.setFixedWidth(SIDEBAR_COMPACT_WIDTH if compact else SIDEBAR_WIDTH)
        margins = (10, 20, 10, 14) if compact else (12, 20, 12, 14)
        self.sidebar.layout().setContentsMargins(*margins)
        self.app_mark.setVisible(not compact)
        self.app_title.setVisible(not compact)
        self._brand_row.setContentsMargins(*((0, 0, 0, 0) if compact else (8, 0, 8, 14)))
        self.search.setVisible(not compact)
        self.search_button.setVisible(compact)
        # Rows of two side by side do not fit a rail: stack them instead.
        vertical = QBoxLayout.Direction.TopToBottom
        horizontal = QBoxLayout.Direction.LeftToRight
        self._footer_row.setDirection(vertical if compact else horizontal)
        self._history_row.setDirection(vertical if compact else self._history_direction())
        for button in (self.back_button, self.undo_button, self.settings_button, *self.nav_buttons):
            button.set_compact(compact)
        centre = Qt.AlignmentFlag.AlignHCenter if compact else Qt.AlignmentFlag(0)
        for row, widget in (
            (self._history_row, self.redo_button),
            (self._footer_row, self.theme_button),
            (self._footer_row, self.fold_button),
        ):
            row.setAlignment(widget, centre)
        self.bot_label.setVisible(self._bot_active and not compact)
        self._show_transcribe_progress()
        self.fold_button.setToolTip(strings.SIDEBAR_EXPAND if compact else strings.SIDEBAR_COLLAPSE)
        self._sync_back()
        self._sync_history()
        self._paint_fold_icon()

    def _history_direction(self) -> QBoxLayout.Direction:
        """A box layout mirrors in RTL; asking for right-to-left there keeps undo on the left."""
        rtl = self.isRightToLeft()
        return QBoxLayout.Direction.RightToLeft if rtl else QBoxLayout.Direction.LeftToRight

    def _paint_fold_icon(self) -> None:
        text = self.palette().color(QPalette.ColorRole.Text)
        self.fold_button.setIcon(sidebar_icon(text, self.isRightToLeft(), not self._compact))

    def _paint_chrome_icons(self) -> None:
        """Repaint every runtime-drawn icon in the current palette."""
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        for button, (painter, section) in zip(self.nav_buttons, self._nav_painters, strict=True):
            button.set_icon(painter(section_ink(section)))
            button._restyle(button.isChecked())
        self.settings_button.set_icon(settings_icon(text))
        self.app_mark.setPixmap(
            voices_icon(QColor(colors().accent_text)).pixmap(NAV_ICON_SIZE, NAV_ICON_SIZE)
        )
        self.theme_button.setIcon(theme_icon(text, self._theme.theme is not Theme.DARK))
        self._search_action.setIcon(search_icon(muted))
        self.search_button.setIcon(search_icon(text))
        self._paint_fold_icon()
        self._paint_back_icon()
        self._paint_history_icons()

    def _paint_back_icon(self) -> None:
        """Muted while Back has nowhere to go: QSS greys the label but cannot reach a
        painted icon."""
        palette = self.palette()
        role = (
            QPalette.ColorRole.Text
            if self.back_button.isEnabled()
            else QPalette.ColorRole.PlaceholderText
        )
        self.back_button.set_icon(back_icon(palette.color(role), self.isRightToLeft()))

    def _paint_history_icons(self) -> None:
        """Repainted on their own, because they change with every edit the user makes.

        A disabled history button says so with a muted glyph: QSS cannot reach a painted
        icon the way it greys the label beside it.
        """
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        self.undo_button.set_icon(
            history_icon(text if self.undo_button.isEnabled() else muted, False)
        )
        self.redo_button.setIcon(
            history_icon(text if self.redo_button.isEnabled() else muted, True)
        )

    def _build_content(self) -> QWidget:
        content = QWidget(objectName="content")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.stack = QStackedWidget()
        for page in (*self._pages, self.search_page):
            self.stack.addWidget(page)
        col.addWidget(self.stack, 1)
        self.toast = Toast(content)
        return content

    def _refresh_counts(self) -> None:
        """Item counts beside the nav labels: 'is there anything in here?' at a glance."""
        try:
            counts = [
                len(self._ws.episodes.list_all()),
                None,  # the board shows the same episodes
                len(self._ws.voices.list_all(ArchiveScope.ACTIVE))
                + len(self._ws.ideas.list_all(ArchiveScope.ACTIVE)),
                self.source_page.pending_count(),  # files waiting to be reviewed
                len(self._ws.tags.list_all()),
                self._ws.trash.count() or None,  # an empty trash shows no number
            ]
        except Exception:
            return  # decoration only; never break the window over it
        for button, count in zip(self.nav_buttons, counts, strict=True):
            button.set_count(count)

    def _install_shortcuts(self) -> None:
        # The everyday moves, from any page: none of them is taken by Windows itself (no
        # Win, Alt+Tab/Space/F4, Ctrl+Esc, Ctrl+Alt — AltGr — or a bare Ctrl+Shift).
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.new_tag)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.find_ideas)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self._theme.toggle)
        QShortcut(QKeySequence.StandardKey.Quit, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)
        # The recorder is one key away wherever the user is, not only inside an episode.
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._record)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_page_filter)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.open_settings())
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
        # Where the app starts is not a move the user made: nothing for Back to undo.
        self.show_page(self._home, remember=False)

    @property
    def _home(self) -> QWidget:
        """The page the app opens on, and where Back and Esc land with nowhere else to go."""
        return self._pages[START_PAGE]

    def _offer_resume(self) -> None:
        """The last opened episode, one click away, without standing between the user and
        the ideas the app opens on."""
        try:
            info = self._ws.episodes.resume()
        except Exception:
            return  # a convenience; never in the way of startup
        if info is None or info.episode.id is None:
            return
        episode_id = info.episode.id
        note_id = info.note.id if info.note is not None else None
        title = shorten(info.episode.title, RESUME_TITLE_CHARS)
        self.toast.show_message(
            strings.RESUME_OFFER.format(title=title),
            strings.RESUME_CONTINUE,
            lambda: self.open_episode(episode_id, note_id),
            show_ms=RESUME_SHOW_MS,
        )

    # navigation ------------------------------------------------------------------------
    def show_page(self, page: QWidget, focus: bool = False, remember: bool = True) -> None:
        """Bring `page` up, recording the one it replaces so Back can undo the move.

        The search results are never recorded: they are not a place the user chose to be,
        and Back through them would be a detour. Search has its own way home
        (`_before_search`).
        """
        current = self.stack.currentWidget()
        if remember and current is not page and current is not self.search_page:
            self._history.push(current)
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
        self._sync_back()

    def navigate(self, index: int, focus: bool = False) -> None:
        self.show_page(self._pages[index], focus=focus)

    def go_back(self) -> None:
        """One step back, onto the page as it was left — filter box, selection, scroll.

        From the search results Back means "stop searching", the same as Esc: the results
        were never somewhere the user navigated to.
        """
        current = self.stack.currentWidget()
        if current is self.search_page:
            self._leave_search()
            return
        entry = self._history.pop_before(current)
        if entry is None:
            if current is not self._home:
                self.show_page(self._home, focus=True, remember=False)
            return
        self.show_page(entry.page, focus=True, remember=False)
        entry.restore()  # after the page is up: showEvent reloads it first
        self._sync_back()

    def _sync_back(self) -> None:
        """Keep the Back button honest about whether it can go anywhere, and where."""
        current = self.stack.currentWidget()
        entry = self._history.peek_before(current)
        target = ""
        if current is self.search_page:  # Back leaves the results the way Esc does
            before = self._before_search
            target = before.title if before is not None else self._home.nav_title
        elif entry is not None:
            target = entry.title
        self.back_button.setEnabled(bool(target))
        label = strings.NAV_BACK_TO.format(page=target) if target else strings.NAV_BACK
        # An episode title can be any length; the sidebar cannot. The tooltip keeps it whole.
        self.back_button.set_label(label)
        self.back_button.setToolTip(
            strings.NAV_BACK_TOOLTIP.format(page=target) if target else strings.NAV_BACK_NOTHING
        )
        self._paint_back_icon()

    def open_episode(self, episode_id: int, note_id: int | None = None) -> None:
        """Every road to an episode leads to the Episodes page, with it selected."""
        self.ideas_page.flush()
        self.show_page(self.episodes_page)
        self.episodes_page.open_episode(episode_id, note_id)

    def open_new_episode(self, episode_id: int) -> None:
        """An episode just started from ideas: open it with its title ready to be named
        (it is called after the first idea until then)."""
        self.open_episode(episode_id)
        self.workspace_page.title_edit.setFocus()
        self.workspace_page.title_edit.selectAll()

    def open_voice(self, voice_id: int) -> None:
        self.show_page(self.ideas_page)
        self.ideas_page.open_voice(voice_id)
        self.ideas_page.focus_editor()

    def open_idea(self, idea_id: int) -> None:
        self.show_page(self.ideas_page)
        self.ideas_page.open_idea(idea_id)

    def focus_search(self) -> None:
        if self._compact:  # the box only exists on the open sidebar
            self.toggle_sidebar()
        self.search.setFocus()
        self.search.selectAll()

    def find_ideas(self) -> None:
        """Ctrl+I: the Ideas page with the caret in its search, from anywhere."""
        self.show_page(self.ideas_page)
        self.ideas_page.focus_filter()

    def new_tag(self) -> None:
        """Ctrl+T: name a new tag from anywhere, without leaving the page — only a tag
        actually made takes the user to the Tags page, to show it."""
        if self.stack.currentWidget() is self.tags_page:
            self.tags_page.create_tag()
            return
        tag_id = self.tags_page.create_tag(name="")
        if tag_id is not None:
            self.show_page(self.tags_page)
            self.tags_page.select(tag_id)

    def focus_page_filter(self) -> None:
        """Ctrl+F narrows what is already in front of the user; Ctrl+K goes looking
        through the whole workspace. On a page with no filter box of its own, the two
        are the same thing."""
        focus_filter = getattr(self.stack.currentWidget(), "focus_filter", None)
        if callable(focus_filter):
            focus_filter()
        else:
            self.focus_search()

    def _leave_search(self, keep_typing: bool = False) -> None:
        """Esc, or Back from the results: put the user down where they started searching.

        `keep_typing`: the box was emptied by hand, which is a pause while retyping, not a
        goodbye — the page comes back behind the box but the caret stays in it.
        """
        entry = self._before_search or NavEntry(self._home)
        self.search_page.reset_scope()  # the next search starts on «active» again
        self.search.clear()
        self.show_page(entry.page, focus=not keep_typing, remember=False)
        entry.restore()
        if keep_typing:
            self.search.setFocus()  # restoring the page may have taken it
        self._sync_back()

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

    # undo / redo -----------------------------------------------------------------------
    def undo(self) -> None:
        self._step_history(forward=False)

    def redo(self) -> None:
        self._step_history(forward=True)

    def _step_history(self, forward: bool) -> None:
        """Take one step through the history, then show the item it landed on.

        A change the user cannot see happening is a change they cannot trust, so the
        page holding the touched item is brought up (or refreshed, when it is already
        the one in front) and the toast names what was put back.
        """
        self.flush_pages()  # a pending autosave is part of what came before
        history = self._ws.history
        try:
            change = history.redo() if forward else history.undo()
        except Exception:
            # The item is gone or changed under it; the entry is already dropped.
            self._sync_history()
            self.toast.show_message(strings.REDO_FAILED if forward else strings.UNDO_FAILED)
            return
        if change is None:
            self.toast.show_message(strings.REDO_NOTHING if forward else strings.UNDO_NOTHING)
            self._sync_history()
            return
        self.events.tags_changed.emit()
        self.events.data_changed.emit()
        if change.kind is ChangeKind.TRASH and forward:
            self.show_page(self.trash_page, remember=False)
        elif (
            change.kind in (ChangeKind.LINKED, ChangeKind.UNLINKED)
            and self.stack.currentWidget() is self.ideas_page
        ):
            # Put into (or taken out of) an episode from the Ideas page: what changed
            # is shown right here, on the idea, so stay rather than jump to the episode.
            self.ideas_page.refresh()
        else:
            self._reveal(change.target)
        self._last_change = history.peek_undo()
        template = strings.REDO_DONE if forward else strings.UNDO_DONE
        self.toast.show_message(template.format(action=describe_change(change)))
        self._sync_history()

    def _reveal(self, target: Target) -> None:
        """Show the item a change touched, staying put when this page already shows it."""
        page = self.stack.currentWidget()
        if page is self.episodes_page and self.workspace_page.episode_id is not None:
            mine = self.workspace_page.episode_id
            if (target.kind is TargetKind.EPISODE and target.item_id == mine) or (
                target.kind is TargetKind.EPISODE_NOTE and target.owner_id == mine
            ):
                note_id = target.item_id if target.kind is TargetKind.EPISODE_NOTE else None
                self.workspace_page.reload(note_id)
                self.episodes_page.refresh(load=False)  # its row, and its season, may differ
                return
        if page is self.board_page and target.kind is TargetKind.EPISODE:
            self.board_page.refresh(focus_id=target.item_id)
            return
        match target.kind:
            case TargetKind.EPISODE:
                self.show_page(self.episodes_page, remember=False)
                self.episodes_page.select(target.item_id)
            case TargetKind.EPISODE_NOTE if target.owner_id is not None:
                self.open_episode(target.owner_id, target.item_id)
            case TargetKind.SEASON:
                self.show_page(self.episodes_page, remember=False)
                self.episodes_page.show_season(target.item_id)
            case TargetKind.VOICE:
                self.open_voice(target.item_id)
            case TargetKind.TIMESTAMP_NOTE if target.owner_id is not None:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.open_note(target.owner_id, target.item_id)
            case TargetKind.IDEA:
                self.open_idea(target.item_id)
            case TargetKind.TAG:
                self.show_page(self.tags_page, remember=False)
                self.tags_page.select(target.item_id)
            case TargetKind.ITEMS:  # only the Ideas page acts on a selection
                if page is self.ideas_page:
                    self.ideas_page.refresh()
                else:
                    self.show_page(self.ideas_page, remember=False)

    def _on_history_touched(self) -> None:
        """After any data change: keep the buttons honest, and offer a way back from
        the changes that take something away."""
        change = self._ws.history.peek_undo()
        if change is not None and change is not self._last_change and change.kind in UNDO_OFFERED:
            self.toast.show_message(
                strings.UNDO_OFFER.format(action=describe_change(change)),
                strings.UNDO,
                self.undo,
            )
        self._last_change = change
        self._sync_history()

    def _sync_history(self) -> None:
        history = self._ws.history
        for button, change, label, template, nothing in (
            (
                self.undo_button,
                history.peek_undo(),
                strings.UNDO,
                strings.UNDO_TOOLTIP,
                strings.UNDO_NOTHING,
            ),
            (
                self.redo_button,
                history.peek_redo(),
                strings.REDO,
                strings.REDO_TOOLTIP,
                strings.REDO_NOTHING,
            ),
        ):
            button.setEnabled(change is not None)
            action = f"{label}: {describe_change(change)}" if change is not None else nothing
            button.setToolTip(template.format(action=action))
        self._paint_history_icons()

    def _watch_for_history_keys(self, _old: QWidget | None, new: QWidget | None) -> None:
        """Follow the focus with the Ctrl+Z filter, instead of watching the whole app."""
        if self._key_filter.target is not None:
            self._key_filter.detach()
        if isinstance(new, QLineEdit | QPlainTextEdit | QTextEdit):
            self._key_filter.attach(new)

    # search ----------------------------------------------------------------------------
    def _run_search(self) -> None:
        query = self.search.text()
        if not query.strip():
            if self.stack.currentWidget() is self.search_page:
                self._leave_search(keep_typing=self.focusWidget() is self.search)
            return
        try:
            result = self._ws.search.search(
                query, scope=self.search_page.scope(), in_content=self.search_page.in_content()
            )
        except Exception as exc:
            show_error(self, exc)
            return
        self.search_page.show_result(result)
        if self.stack.currentWidget() is not self.search_page:
            # Snapshot now, while the page is still the one the user was reading.
            page = self.stack.currentWidget()
            self._before_search = NavEntry(page, capture_state(page))
            self.show_page(self.search_page, remember=False)

    def _open_hit(self, hit: SearchHit) -> None:
        """Open what a search hit points at — and leave a way back to where the search
        started, since the results page itself is about to be gone."""
        query = self.search.text()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        if self._before_search is not None:
            self._history.push_entry(self._before_search)
            self._before_search = None
        self.search_page.reset_scope()
        match hit.kind:
            case SearchKind.EPISODE:
                self.show_page(self.episodes_page, remember=False)
                self.episodes_page.select(hit.source_id)
            case SearchKind.EPISODE_NOTE if hit.owner_id is not None:
                self.open_episode(hit.owner_id, hit.source_id)
            case SearchKind.VOICE:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.open_voice(hit.source_id)
            case SearchKind.TRANSCRIPT if hit.owner_id is not None:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.open_transcript(hit.owner_id, query)
            case SearchKind.TIMESTAMP_NOTE if hit.owner_id is not None:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.open_note(hit.owner_id, hit.source_id)
            case SearchKind.IDEA_NOTE:
                self.show_page(self.ideas_page, remember=False)
                self.ideas_page.open_idea(hit.source_id)
            case SearchKind.TAG:
                self.show_page(self.tags_page, remember=False)
                self.tags_page.select(hit.source_id)
            case _:
                self.show_page(self._pages[0], remember=False)
        self._sync_back()

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

    # settings, recorder, inbox, bot ------------------------------------------------------
    def open_settings(self, tab: int = TAB_GENERAL, export: bool = False) -> bool:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self, self._ws, self.bot, IDEA_HOTKEY_LABEL)
            self._settings_dialog.data_replaced.connect(self._on_data_replaced)
            self._settings_dialog.restart_requested.connect(self._restart)
        return self._settings_dialog.open_at(tab, self.hotkey.registered, export=export)

    def _restart(self) -> None:
        """Close normally (so every autosave and the geometry are written) and let
        app.main() start the app again once this instance is gone."""
        self.restart_requested = True
        QTimer.singleShot(0, self.close)

    def _check_backup(self) -> None:
        """Once a week (by default), on opening: time to take a backup?

        Answered in the app itself, where the export is one click away — not a
        notification that sends the user looking for the right setting.
        """
        try:
            reminder = self._ws.backup.reminder()
        except Exception:
            return  # a reminder must never get in the way of starting the app
        if reminder is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(strings.BACKUP_REMINDER_TITLE)
        box.setText(
            strings.BACKUP_REMINDER_NEVER
            if reminder.never_backed_up
            else strings.BACKUP_REMINDER_BODY.format(days=local_digits(reminder.days_since))
        )
        box.setInformativeText(strings.BACKUP_REMINDER_HINT)
        now_button = box.addButton(strings.BACKUP_NOW, QMessageBox.ButtonRole.AcceptRole)
        now_button.setObjectName("primary")
        tomorrow = box.addButton(strings.BACKUP_TOMORROW, QMessageBox.ButtonRole.RejectRole)
        box.addButton(strings.BACKUP_LATER, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(now_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is now_button:
            self.open_settings(TAB_DATA, export=True)
        elif clicked is tomorrow:
            self._ws.backup.snooze_reminder(days=1, now=datetime.now(UTC))
        # "Later" (or closing the box) asks again next time the app opens.

    def _purge_trash(self) -> int:
        """Delete for good what has spent the full period in the trash."""
        try:
            return len(self._ws.trash.purge_expired())
        except Exception:
            return 0  # tried again within the hour; never break the window over it

    def _on_purge_timer(self) -> None:
        purged = self._purge_trash()
        if purged:
            self.events.data_changed.emit()
            self._announce_purge(purged)

    def _announce_purge(self, purged: int) -> None:
        self.toast.show_message(
            strings.TRASH_AUTO_PURGED.format(n=local_digits(purged), days=local_digits(TRASH_DAYS))
        )

    def flush_pages(self) -> None:
        """Write pending autosaves (before export/import)."""
        self.ideas_page.flush()
        self.workspace_page.flush()

    def _on_data_replaced(self, _report: object) -> None:
        """An import replaced every row: drop anything that points at old data."""
        self.ideas_page.clear_editor()  # stops the player on a file that may be gone
        self._history.clear()
        self._ws.history.clear()  # its entries name rows that no longer exist
        self._last_change = None
        self.toast.dismiss()
        self._before_search = None
        self.events.tags_changed.emit()
        self.events.data_changed.emit()
        self.show_page(self._home, remember=False)  # a fresh start, like opening the app

    def _on_bot_status(self, status: BotStatus, _detail: str) -> None:
        self._bot_active = status is not BotStatus.STOPPED
        self.bot_label.setVisible(self._bot_active and not self._compact)
        text = strings.BOT_STATUS.get(status.value, status.value)
        self.bot_label.setText(strings.BOT_SIDEBAR.format(status=text))

    def _show_transcribe_progress(self) -> None:
        jobs = self.transcription_jobs
        self.transcribe_label.setVisible(jobs.batching and not self._compact)
        if not jobs.batching:
            return
        n = local_digits(min(jobs.batch_done + 1, jobs.batch_total))
        total = local_digits(jobs.batch_total)
        if jobs.fraction >= 0:
            percent = local_digits(int(jobs.fraction * 100))
            text = strings.TR_ALL_SIDEBAR_PERCENT.format(n=n, total=total, percent=percent)
        else:
            text = strings.TR_ALL_SIDEBAR.format(n=n, total=total)
        self.transcribe_label.setText(text)

    def _on_voices_secured(self, copied: int) -> None:
        if not copied:
            return
        self.events.data_changed.emit()
        self.ideas_page.external_change()
        self.ideas_page.status.setText(strings.VOICES_SECURED.format(n=local_digits(copied)))
        QTimer.singleShot(10000, lambda: self.ideas_page.status.setText(""))

    def _on_bot_item(self, ref: ItemRef) -> None:
        self.events.tags_changed.emit()  # the bot may have created tags
        self.events.data_changed.emit()
        self.ideas_page.external_change()
        received = (
            strings.BOT_RECEIVED_IDEA if ref.kind is ItemKind.IDEA else strings.BOT_RECEIVED_VOICE
        )
        self.ideas_page.status.setText(received)
        QTimer.singleShot(6000, lambda: self.ideas_page.status.setText(""))

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
        self.theme_button.setToolTip(
            (strings.THEME_TO_LIGHT if dark else strings.THEME_TO_DARK) + "  (Ctrl+Shift+T)"
        )
        self._paint_chrome_icons()
        set_native_dark_title_bar(self, dark)
        set_native_dark_title_bar(self.inbox, dark)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        set_native_dark_title_bar(self, self._theme.theme is Theme.DARK)
        if self._first_show:
            self._first_show = False
            self.hotkey.register(int(self.winId()), *IDEA_HOTKEY)
            self.bot.restart()  # quietly does nothing unless enabled with a token
            # Voices added before the store existed still play from the recorder's folder.
            run_async(self._ws.voices.secure_external, self._on_voices_secured, lambda _e: None)
            QTimer.singleShot(BACKUP_CHECK_DELAY_MS, self._check_backup)
            if self._auto_purged:  # the one toast at a time: news of a deletion comes first
                purged = self._auto_purged
                QTimer.singleShot(0, lambda: self._announce_purge(purged))
            else:
                QTimer.singleShot(0, self._offer_resume)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ideas_page.flush()  # pending autosaves must not be lost
        self.workspace_page.flush()
        self._ws.settings.set_window_geometry(bytes(self.saveGeometry().data()))
        self.hotkey.unregister()
        self.bot.stop()
        self.transcription_jobs.stop()
        self.inbox.close()
        self.player.shutdown()
        super().closeEvent(event)
