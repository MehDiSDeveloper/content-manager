"""Light/dark theming: Fusion style + palette + a small stylesheet, Windows 11 colors."""

import contextlib
import ctypes
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from podcast_workspace.paths import resources_dir
from podcast_workspace.services.settings_service import SettingsService, Theme

PREFERRED_FONTS = ("Vazirmatn", "Vazir", "Segoe UI")
FONT_POINT_SIZE = 10


@dataclass(frozen=True)
class Colors:
    window: str
    sidebar: str
    surface: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    hover: str
    accent_soft: str


LIGHT = Colors(
    window="#f9f9f9",
    sidebar="#f0f0f0",
    surface="#ffffff",
    border="#e5e5e5",
    text="#1b1b1b",
    muted="#616161",
    accent="#005fb8",
    accent_text="#ffffff",
    hover="#e8e8e8",
    accent_soft="#e3eefa",
)
DARK = Colors(
    window="#202020",
    sidebar="#1a1a1a",
    surface="#2b2b2b",
    border="#3a3a3a",
    text="#f3f3f3",
    muted="#a8a8a8",
    accent="#60cdff",
    accent_text="#000000",
    hover="#2f2f2f",
    accent_soft="#1d3848",
)


def load_fonts(app: QApplication) -> str:
    """Register bundled fonts (drop Vazirmatn .ttf files into resources/fonts) and pick one."""
    fonts_dir = resources_dir() / "fonts"
    for font_file in sorted(fonts_dir.glob("*.[ot]tf")):
        QFontDatabase.addApplicationFont(str(font_file))
    families = set(QFontDatabase.families())
    family = next((f for f in PREFERRED_FONTS if f in families), app.font().family())
    font = app.font()
    font.setFamily(family)
    font.setPointSize(FONT_POINT_SIZE)
    app.setFont(font)
    return family


def _palette(c: Colors) -> QPalette:
    p = QPalette()
    role = QPalette.ColorRole
    p.setColor(role.Window, QColor(c.window))
    p.setColor(role.WindowText, QColor(c.text))
    p.setColor(role.Base, QColor(c.surface))
    p.setColor(role.AlternateBase, QColor(c.hover))
    p.setColor(role.Text, QColor(c.text))
    p.setColor(role.Button, QColor(c.surface))
    p.setColor(role.ButtonText, QColor(c.text))
    p.setColor(role.Highlight, QColor(c.accent))
    p.setColor(role.HighlightedText, QColor(c.accent_text))
    p.setColor(role.PlaceholderText, QColor(c.muted))
    p.setColor(role.ToolTipBase, QColor(c.surface))
    p.setColor(role.ToolTipText, QColor(c.text))
    p.setColor(role.Link, QColor(c.accent))
    p.setColor(QPalette.ColorGroup.Disabled, role.Text, QColor(c.muted))
    p.setColor(QPalette.ColorGroup.Disabled, role.ButtonText, QColor(c.muted))
    return p


STALE = "#d97706"


def _stylesheet(c: Colors) -> str:
    return f"""
    QMainWindow, #content {{ background: {c.window}; }}
    #sidebar {{ background: {c.sidebar}; border-left: 1px solid {c.border}; }}
    #appTitle {{ font-size: 13pt; font-weight: 600; color: {c.text}; }}
    #pageTitle {{ font-size: 18pt; font-weight: 600; color: {c.text}; }}
    #editorTitle {{ font-size: 15pt; font-weight: 600; color: {c.text}; }}
    #dialogTitle {{ font-size: 13pt; font-weight: 600; }}
    #emptyHint {{ font-size: 11pt; color: {c.muted}; padding: 32px; }}
    #muted {{ color: {c.muted}; }}
    #warning {{ color: {STALE}; }}

    #navButton {{
        text-align: right; padding: 9px 14px; border: none; border-radius: 6px;
        background: transparent; color: {c.text};
    }}
    #navButton:hover {{ background: {c.hover}; }}
    #navButton:checked {{
        background: {c.surface}; font-weight: 600; border-right: 3px solid {c.accent};
    }}
    #navButton:focus {{ border: 2px solid {c.accent}; }}

    QPushButton {{
        background: {c.surface}; color: {c.text};
        border: 1px solid {c.border}; border-radius: 6px; padding: 7px 16px;
    }}
    QPushButton:hover {{ background: {c.hover}; }}
    QPushButton:focus {{ border: 2px solid {c.accent}; padding: 6px 15px; }}
    QPushButton:disabled {{ color: {c.muted}; }}
    QPushButton#primary {{
        background: {c.accent}; color: {c.accent_text}; font-weight: 600;
        border: 2px solid {c.accent}; padding: 6px 15px;
    }}
    QPushButton#primary:focus {{ border: 2px solid {c.text}; }}
    QPushButton#danger {{ color: #dc2626; }}

    QLineEdit, QPlainTextEdit, QComboBox {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border};
        border-radius: 6px; padding: 7px 10px; selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border: 2px solid {c.accent}; padding: 6px 9px;
    }}
    QLineEdit#titleEdit {{ font-size: 16pt; font-weight: 600; padding: 8px 12px; }}
    QLineEdit#searchBar {{ padding: 9px 14px; border-radius: 8px; font-size: 11pt; }}
    QPlainTextEdit#ideaText {{ font-size: 12pt; padding: 12px; }}

    QListWidget, QTreeWidget {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px;
        outline: none; padding: 4px;
    }}
    QListWidget::item, QTreeWidget::item {{ border-radius: 6px; padding: 4px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c.hover}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c.accent}; color: {c.accent_text};
    }}
    QListWidget:focus, QTreeWidget:focus {{ border: 2px solid {c.accent}; }}
    QListWidget#suggestions {{ padding: 2px; }}
    QListWidget#suggestions::item {{ padding: 6px 8px; }}
    QListWidget#results::item {{ margin: 1px 0; }}
    QListWidget#results::item:selected {{
        background: {c.hover}; color: {c.text}; border: 2px solid {c.accent};
    }}
    QHeaderView::section {{
        background: {c.surface}; color: {c.muted}; border: none; padding: 6px 8px;
        border-bottom: 1px solid {c.border};
    }}

    #kindBadge {{
        background: {c.hover}; color: {c.muted}; border-radius: 4px; padding: 1px 8px;
        font-size: 9pt;
    }}
    #hitTitle {{ font-size: 11pt; color: {c.text}; }}
    #hitSnippet {{ color: {c.muted}; }}
    #chipClose {{ border: none; background: transparent; color: {c.muted}; padding: 0 4px; }}
    #chipClose:hover {{ color: {c.text}; }}

    #sectionTitle {{ font-size: 12pt; font-weight: 600; color: {c.text}; }}
    #clock {{ font-size: 12pt; font-weight: 600; color: {c.text}; min-width: 64px; }}
    QPushButton#playButton {{
        background: {c.accent}; border: 2px solid {c.accent}; border-radius: 24px; padding: 0;
    }}
    QPushButton#playButton:hover {{ background: {c.accent}; border-color: {c.text}; }}
    QPushButton#playButton:focus {{ border: 2px solid {c.text}; padding: 0; }}
    QPushButton#playButton:disabled {{ background: {c.hover}; border-color: {c.hover}; }}
    QPushButton#transportButton {{
        background: transparent; border: 1px solid transparent; border-radius: 20px; padding: 0;
    }}
    QPushButton#transportButton:hover {{ background: {c.hover}; }}
    QPushButton#transportButton:focus {{ border: 2px solid {c.accent}; padding: 0; }}
    QToolButton#speedButton {{
        background: transparent; color: {c.text}; border: 1px solid {c.border};
        border-radius: 6px; padding: 4px 10px; min-width: 44px;
    }}
    QToolButton#speedButton:hover {{ background: {c.hover}; }}
    QToolButton#speedButton::menu-indicator {{ image: none; width: 0; }}

    #noteScroll, #noteHost {{ background: transparent; }}
    #noteRow {{ background: transparent; border-radius: 6px; border: 2px solid transparent; }}
    #noteRow:hover {{ background: {c.hover}; }}
    #noteRow[active="true"] {{
        background: {c.accent_soft}; border-right: 3px solid {c.accent};
    }}
    #noteRow:focus {{ border: 2px solid {c.accent}; }}
    #noteText {{ color: {c.text}; font-size: 10.5pt; }}
    QToolButton#gotoButton {{
        background: {c.hover}; color: {c.muted}; border: none; border-radius: 5px;
        padding: 3px 8px; font-weight: 600;
    }}
    QToolButton#gotoButton:hover {{ color: {c.text}; }}
    #noteRow[active="true"] QToolButton#gotoButton {{
        background: {c.accent}; color: {c.accent_text};
    }}
    QToolButton#captureChip {{
        background: {c.hover}; color: {c.muted}; border: 1px solid {c.border};
        border-radius: 6px; padding: 6px 10px; min-width: 52px;
    }}
    QToolButton#captureChip[captured="true"] {{
        background: {c.accent}; color: {c.accent_text}; border-color: {c.accent};
    }}

    #fieldLabel {{ color: {c.muted}; font-size: 9.5pt; font-weight: 600; }}
    QPushButton#flatButton {{
        background: transparent; border: 1px solid transparent; color: {c.accent};
        padding: 4px 10px;
    }}
    QPushButton#flatButton:hover {{ background: {c.hover}; }}
    QPushButton#flatButton:focus {{ border: 2px solid {c.accent}; padding: 3px 9px; }}
    QPushButton#recordButton {{ color: #dc2626; font-weight: 600; }}
    QToolButton#backButton {{
        background: transparent; color: {c.muted}; border: none; border-radius: 6px;
        padding: 6px 10px;
    }}
    QToolButton#backButton:hover {{ background: {c.hover}; color: {c.text}; }}
    QToolButton#backButton:focus {{ border: 2px solid {c.accent}; }}
    #staleBadge {{
        color: {STALE}; border: 1px solid {STALE}; border-radius: 10px; padding: 2px 10px;
        font-size: 9pt; font-weight: 600;
    }}
    #sidePanel {{ background: {c.sidebar}; border: 1px solid {c.border}; border-radius: 10px; }}
    #sidePanel QListWidget {{ background: {c.surface}; }}
    QLineEdit#noteTitle {{ font-size: 12pt; font-weight: 600; }}
    QPlainTextEdit#noteBody {{ font-size: 11.5pt; padding: 12px; }}
    QTabBar#noteTabs::tab {{
        background: transparent; color: {c.muted}; padding: 6px 14px; margin: 0 2px;
        border: none; border-bottom: 2px solid transparent; max-width: 220px;
    }}
    QTabBar#noteTabs::tab:hover {{ color: {c.text}; }}
    QTabBar#noteTabs::tab:selected {{
        color: {c.text}; font-weight: 600; border-bottom: 2px solid {c.accent};
    }}
    QTabBar#noteTabs:focus {{ border: 1px dashed {c.accent}; }}

    #boardFrame {{ background: {c.sidebar}; border-radius: 10px; }}
    #columnTitle {{ font-weight: 600; color: {c.text}; }}
    QListWidget#boardColumn {{ background: transparent; border: none; padding: 0; }}
    QListWidget#boardColumn::item, QListWidget#boardColumn::item:selected,
    QListWidget#boardColumn::item:hover {{ background: transparent; color: {c.text}; }}
    QListWidget#boardColumn:focus {{ border: none; }}
    #boardScroll, #boardHost {{ background: transparent; }}

    #resumeCard {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 14px; }}
    #eyebrow {{ color: {c.accent}; font-weight: 600; font-size: 10pt; }}
    #resumeTitle {{ font-size: 20pt; font-weight: 600; color: {c.text}; }}
    #resumeNext {{ font-size: 13pt; color: {c.text}; }}
    #resumeNoteTitle {{ font-size: 11pt; font-weight: 600; color: {c.text}; }}

    #inboxFrame {{
        background: {c.surface}; border: 1px solid {c.accent}; border-radius: 12px;
    }}
    QPlainTextEdit#inboxText {{ font-size: 12pt; }}

    QToolTip {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border}; padding: 4px;
    }}
    """


def set_native_dark_title_bar(widget: QWidget, dark: bool) -> None:
    """Windows 10 1809+/11: ask DWM for a dark or light caption bar."""
    if sys.platform != "win32":
        return
    dwmwa_use_immersive_dark_mode = 20
    value = ctypes.c_int(1 if dark else 0)
    with contextlib.suppress(OSError):
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(widget.winId())),
            dwmwa_use_immersive_dark_mode,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )


def system_theme() -> Theme:
    scheme = QGuiApplication.styleHints().colorScheme()
    return Theme.DARK if scheme == Qt.ColorScheme.Dark else Theme.LIGHT


class ThemeManager(QObject):
    changed = Signal(Theme)

    def __init__(self, app: QApplication, settings: SettingsService) -> None:
        super().__init__(app)
        self._app = app
        self._settings = settings
        self._theme = settings.theme() or system_theme()
        app.setStyle("Fusion")

    @property
    def theme(self) -> Theme:
        return self._theme

    def apply(self, theme: Theme | None = None) -> None:
        self._theme = theme or self._theme
        colors = DARK if self._theme is Theme.DARK else LIGHT
        self._app.setPalette(_palette(colors))
        self._app.setStyleSheet(_stylesheet(colors))
        for window in self._app.topLevelWidgets():
            set_native_dark_title_bar(window, self._theme is Theme.DARK)
        self.changed.emit(self._theme)

    def toggle(self) -> None:
        new = Theme.LIGHT if self._theme is Theme.DARK else Theme.DARK
        self._settings.set_theme(new)
        self.apply(new)
