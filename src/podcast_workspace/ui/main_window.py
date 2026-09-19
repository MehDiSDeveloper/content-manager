"""Main window shell: sidebar (right, RTL) + content area. No real screens yet."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.services.settings_service import SettingsService, Theme
from podcast_workspace.ui import strings
from podcast_workspace.ui.theme import ThemeManager, set_native_dark_title_bar

SIDEBAR_WIDTH = 248


class MainWindow(QMainWindow):
    def __init__(self, settings: SettingsService, theme: ThemeManager) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self.setWindowTitle(strings.APP_NAME)
        self.setMinimumSize(900, 600)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        self.content = self._build_content()
        # In a right-to-left layout the first widget sits on the right.
        layout.addWidget(self.sidebar)
        layout.addWidget(self.content, 1)
        self.setCentralWidget(root)

        self._install_shortcuts()
        theme.changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme.theme)

        geometry = settings.window_geometry()
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(1200, 760)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        col = QVBoxLayout(sidebar)
        col.setContentsMargins(20, 24, 20, 20)
        col.setSpacing(12)
        col.addWidget(QLabel(strings.APP_NAME, objectName="appTitle"))
        col.addStretch(1)
        self.theme_button = QPushButton()
        self.theme_button.setToolTip(strings.THEME_TOOLTIP)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._theme.toggle)
        col.addWidget(self.theme_button)
        return sidebar

    def _build_content(self) -> QStackedWidget:
        stack = QStackedWidget(objectName="content")
        empty = QWidget()
        col = QVBoxLayout(empty)
        col.setContentsMargins(64, 64, 64, 64)
        col.addStretch(1)
        title = QLabel(strings.EMPTY_TITLE, objectName="emptyTitle")
        hint = QLabel(strings.EMPTY_HINT, objectName="emptyHint")
        hint.setWordWrap(True)
        for label in (title, hint):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(label)
        col.addStretch(2)
        stack.addWidget(empty)
        return stack

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self._theme.toggle)
        QShortcut(QKeySequence.StandardKey.Quit, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        # F6 moves focus between the main panes, as in Windows apps.
        QShortcut(QKeySequence("F6"), self, activated=self._cycle_pane_focus)

    def _cycle_pane_focus(self) -> None:
        focus = QApplication.focusWidget()
        in_sidebar = focus is not None and self.sidebar.isAncestorOf(focus)
        target = self.content if in_sidebar else self.sidebar
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
        target.focusNextChild()

    def _on_theme_changed(self, theme: Theme) -> None:
        dark = theme is Theme.DARK
        self.theme_button.setText(strings.THEME_TO_LIGHT if dark else strings.THEME_TO_DARK)
        set_native_dark_title_bar(self, dark)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        set_native_dark_title_bar(self, self._theme.theme is Theme.DARK)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._settings.set_window_geometry(bytes(self.saveGeometry().data()))
        super().closeEvent(event)
