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


def _stylesheet(c: Colors) -> str:
    return f"""
    QMainWindow, #content {{ background: {c.window}; }}
    #sidebar {{ background: {c.sidebar}; border-left: 1px solid {c.border}; }}
    #appTitle {{ font-size: 13pt; font-weight: 600; color: {c.text}; }}
    #emptyTitle {{ font-size: 20pt; font-weight: 600; color: {c.text}; }}
    #emptyHint {{ font-size: 11pt; color: {c.muted}; }}
    QPushButton {{
        background: {c.surface}; color: {c.text};
        border: 1px solid {c.border}; border-radius: 6px; padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {c.hover}; }}
    QPushButton:focus {{ border: 2px solid {c.accent}; }}
    QPushButton#primary {{
        background: {c.accent}; color: {c.accent_text}; border: none;
    }}
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
