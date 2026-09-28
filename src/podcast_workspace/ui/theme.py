"""Light/dark theming: Fusion style + palette + one stylesheet, in soft pastel colours.

Every colour the UI uses comes from here. Pastels are for fills (buttons, selections,
section glyphs, board columns); each pastel has a deeper "ink" of the same hue for
strokes and text on it, so a pastel never has to carry text by itself.
"""

import contextlib
import ctypes
import os
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from podcast_workspace.paths import resources_dir
from podcast_workspace.services.settings_service import SettingsService, Theme

PREFERRED_FONTS = ("Vazirmatn", "Vazir", "Segoe UI")
FONT_POINT_SIZE = 10.5
# Grayscale FreeType draws a touch lighter than ClearType; Medium brings body text back
# to a solid stroke. Code that resets a font after a bold run resets it to this.
TEXT_WEIGHT = QFont.Weight.Medium


@dataclass(frozen=True)
class Colors:
    window: str
    sidebar: str
    surface: str
    border: str
    text: str
    muted: str
    accent: str  # pastel fill: primary button, play button, waveform progress
    accent_text: str  # ink on the accent fill
    accent_strong: str  # focus rings, links, active marks
    accent_soft: str  # selected rows, chosen tab
    hover: str
    panel: str
    danger: str
    danger_soft: str
    warning: str
    warning_soft: str


LIGHT = Colors(
    window="#f8f6fc",
    sidebar="#f1eef9",
    surface="#ffffff",
    border="#e6e1f1",
    text="#2a2640",
    muted="#7c7794",
    accent="#cbbffb",
    accent_text="#2a1f63",
    accent_strong="#7866dc",
    accent_soft="#efebfe",
    hover="#f4f1fb",
    panel="#f4f1fb",
    danger="#c8475f",
    danger_soft="#fde8ec",
    warning="#b7700f",
    warning_soft="#fdf1dc",
)
DARK = Colors(
    window="#1d1b26",
    sidebar="#18161f",
    surface="#262431",
    border="#363345",
    text="#eceaf4",
    muted="#a19cb5",
    accent="#bcaef8",
    accent_text="#1c1638",
    accent_strong="#c8bcff",
    accent_soft="#342d55",
    hover="#2d2a3a",
    panel="#221f2c",
    danger="#f29aab",
    danger_soft="#3d2530",
    warning="#f0b86a",
    warning_soft="#3a2f20",
)

# One hue per sidebar section and per production stage: (ink on light, ink on dark).
SECTION_INKS: dict[str, tuple[str, str]] = {
    "episodes": ("#7462d6", "#c3b8fb"),
    "board": ("#2f9471", "#9ddfc5"),
    "voices": ("#cf6f47", "#f7bea3"),
    "source": ("#3f8fce", "#a9d2f5"),
    "ideas": ("#b1850f", "#f1d98a"),
    "tags": ("#c9577f", "#f4b0ca"),
    "trash": ("#6f7686", "#b9c0cf"),
}
STATUS_INKS: dict[str, tuple[str, str]] = {
    "idea": ("#b1850f", "#f1d98a"),
    "outline": ("#7462d6", "#c3b8fb"),
    "recorded": ("#cf6f47", "#f7bea3"),
    "script_ready": ("#3f8fce", "#a9d2f5"),
    "edited": ("#c9577f", "#f4b0ca"),
    "published": ("#2f9471", "#9ddfc5"),
}

_dark = False


def colors() -> Colors:
    """The colours of the theme in effect (for widgets that paint themselves)."""
    return DARK if _dark else LIGHT


def section_ink(key: str) -> QColor:
    light, dark = SECTION_INKS.get(key, (LIGHT.muted, DARK.muted))
    return QColor(dark if _dark else light)


def status_ink(key: str) -> QColor:
    light, dark = STATUS_INKS.get(key, (LIGHT.muted, DARK.muted))
    return QColor(dark if _dark else light)


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})"


def configure_text_rendering() -> None:
    """Pick the font rasteriser; must run before the QApplication exists.

    Qt's default DirectWrite engine gives Vazirmatn ClearType colour fringes and stepped
    curves, worst on low-PPI screens at fractional scaling (110%) and on the dark theme,
    where Persian text reads as dotted. FreeType renders it smooth and fringe-free.
    An explicit QT_QPA_PLATFORM or -platform argument still wins.
    """
    if sys.platform != "win32" or "QT_QPA_PLATFORM" in os.environ or "-platform" in sys.argv:
        return
    os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"


def load_fonts(app: QApplication) -> str:
    """Register the bundled fonts (resources/fonts, Vazirmatn) and pick one."""
    fonts_dir = resources_dir() / "fonts"
    for font_file in sorted(fonts_dir.glob("*.[ot]tf")):
        QFontDatabase.addApplicationFont(str(font_file))
    families = set(QFontDatabase.families())
    family = next((f for f in PREFERRED_FONTS if f in families), app.font().family())
    font = app.font()
    font.setFamily(family)
    font.setPointSizeF(FONT_POINT_SIZE)
    font.setWeight(TEXT_WEIGHT)
    # Vazirmatn's curves thin out under full hinting at text sizes; light hinting keeps
    # baselines sharp without bending the curves.
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias
    )
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
    p.setColor(role.Link, QColor(c.accent_strong))
    p.setColor(role.Mid, QColor(c.border))
    p.setColor(role.Dark, QColor(c.border))
    p.setColor(role.Light, QColor(c.surface))
    for disabled in (role.Text, role.ButtonText, role.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, disabled, QColor(c.muted))
    return p


def _tinted_rules(dark: bool) -> str:
    """Per-section and per-stage rules: sidebar glyph tiles, board columns, status dots."""
    rules = []
    for key, (light_ink, dark_ink) in SECTION_INKS.items():
        ink = dark_ink if dark else light_ink
        rules.append(
            f'#navGlyph[section="{key}"] {{ background: {_rgba(ink, 0.2 if dark else 0.15)}; }}'
        )
    for key, (light_ink, dark_ink) in STATUS_INKS.items():
        ink = dark_ink if dark else light_ink
        rules.append(
            f'#boardFrame[status="{key}"] {{ background: {_rgba(ink, 0.07 if dark else 0.08)};'
            f" border: 1px solid {_rgba(ink, 0.14 if dark else 0.16)}; }}"
        )
        rules.append(f'#statusDot[status="{key}"] {{ background: {ink}; }}')
    return "\n".join(rules)


def _stylesheet(c: Colors, dark: bool, rtl: bool) -> str:
    on_soft = c.text if dark else c.accent_text  # text on an accent_soft fill
    # QSS does not mirror: the rail's inner edge is on the left in RTL, the right in LTR.
    inner_edge = "left" if rtl else "right"
    return f"""
    QMainWindow, #content {{ background: {c.window}; }}
    #sidebar {{ background: {c.sidebar}; border-{inner_edge}: 1px solid {c.border}; }}
    #appTitle {{ font-size: 13.5pt; font-weight: 700; color: {c.text}; }}
    #appMark {{ background: {c.accent}; border-radius: 11px; }}
    #pageTitle {{ font-size: 20pt; font-weight: 700; color: {c.text}; }}
    #editorTitle {{ font-size: 15pt; font-weight: 700; color: {c.text}; }}
    #dialogTitle {{ font-size: 13pt; font-weight: 700; }}
    #emptyHint {{ font-size: 11pt; color: {c.muted}; padding: 32px; }}
    #muted {{ color: {c.muted}; }}
    #warning {{ color: {c.warning}; }}

    /* Padding comes from the button's own layout (glyph tile + label + count). */
    #navButton {{
        padding: 0; border: 2px solid transparent; border-radius: 12px;
        background: transparent; color: {c.text};
    }}
    #navButton:hover {{ background: {c.hover}; }}
    #navButton:checked {{ background: {c.surface}; border-color: {c.border}; }}
    #navButton:focus {{ border: 2px solid {c.accent_strong}; }}
    #navButton:disabled {{ color: {c.muted}; background: transparent; }}
    #navGlyph {{ background: transparent; border-radius: 9px; }}
    QToolButton#chromeButton {{
        background: transparent; border: 2px solid transparent; border-radius: 12px;
        padding: 7px; color: {c.text};
    }}
    QToolButton#chromeButton:hover {{ background: {c.hover}; }}
    QToolButton#chromeButton:focus {{ border-color: {c.accent_strong}; }}
    QToolButton#chromeButton::menu-indicator {{ image: none; width: 0; }}
    QLineEdit#sidebarSearch {{ padding: 8px 10px; border-radius: 12px; }}
    QLineEdit#sidebarSearch:focus {{ padding: 7px 9px; }}

    QPushButton {{
        background: {c.surface}; color: {c.text};
        border: 1px solid {c.border}; border-radius: 10px; padding: 8px 18px;
    }}
    QPushButton:hover {{ background: {c.hover}; border-color: {c.accent}; }}
    QPushButton:pressed {{ background: {c.accent_soft}; }}
    QPushButton:focus {{ border: 2px solid {c.accent_strong}; padding: 7px 17px; }}
    QPushButton:disabled {{ color: {c.muted}; background: {c.panel}; border-color: {c.border}; }}
    QPushButton#primary {{
        background: {c.accent}; color: {c.accent_text}; font-weight: 700;
        border: 2px solid {c.accent}; padding: 7px 18px;
    }}
    QPushButton#primary:hover {{ border-color: {c.accent_strong}; }}
    QPushButton#primary:pressed {{ background: {c.accent_strong}; color: {c.surface}; }}
    QPushButton#primary:focus {{ border: 2px solid {c.accent_strong}; }}
    QPushButton#primary:disabled {{
        background: {c.panel}; color: {c.muted}; border-color: {c.border};
    }}
    QPushButton#danger {{ color: {c.danger}; }}
    QPushButton#danger:hover {{ background: {c.danger_soft}; border-color: {c.danger}; }}

    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border};
        border-radius: 10px; padding: 8px 11px; selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {c.accent}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 2px solid {c.accent_strong}; padding: 7px 10px;
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {c.panel}; color: {c.muted}; }}
    /* Not styled: a stylesheet on QComboBox makes Qt draw the drop-down as a separate
       square hanging outside the rounded frame in RTL. Fusion's own combo is correct. */
    QComboBox {{ min-width: 132px; padding: 5px 9px; }}
    QComboBox QAbstractItemView {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border};
        selection-background-color: {c.accent_soft}; selection-color: {c.text};
        outline: none; padding: 4px;
    }}
    QLineEdit#titleEdit {{ font-size: 16pt; font-weight: 700; padding: 9px 13px; }}
    QLineEdit#titleEdit:focus {{ padding: 8px 12px; }}
    QLineEdit#searchBar {{ padding: 10px 14px; border-radius: 12px; font-size: 11pt; }}
    QLineEdit#searchBar:focus {{ padding: 9px 13px; }}
    /* A page's own filter box: a quieter field than an editable value, because it
       changes what you see and not what you have. */
    QLineEdit#listFilter {{
        padding: 8px 11px; border-radius: 12px; background: {c.panel};
        border-color: {c.panel};
    }}
    QLineEdit#listFilter:hover {{ border-color: {c.border}; }}
    QLineEdit#listFilter:focus {{ background: {c.surface}; padding: 7px 10px; }}
    QPlainTextEdit#ideaText {{ font-size: 12.5pt; padding: 14px; }}
    QPlainTextEdit#ideaText:focus {{ padding: 13px; }}

    QListWidget, QTreeWidget {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 14px;
        outline: none; padding: 6px;
    }}
    QListWidget::item, QTreeWidget::item {{
        border-radius: 9px; padding: 5px; margin: 1px 0; color: {c.text};
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c.hover}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c.accent_soft}; color: {on_soft};
    }}
    QListWidget:focus, QTreeWidget:focus {{ border: 1px solid {c.accent_strong}; }}
    /* A row spans several columns: one flat band reads better than rounded pieces. */
    QTreeWidget::item {{ border-radius: 0; margin: 0; padding: 6px 4px; }}
    QListWidget#suggestions {{ padding: 3px; }}
    QListWidget#suggestions::item {{ padding: 7px 9px; }}
    QListWidget#results::item {{ margin: 2px 0; border: 1px solid transparent; }}
    QListWidget#results::item:hover {{ border-color: {c.border}; }}
    QListWidget#results::item:selected {{
        background: {c.accent_soft}; color: {c.text}; border: 1px solid {c.accent_strong};
    }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: transparent; color: {c.muted}; border: none; padding: 6px 8px;
        border-bottom: 1px solid {c.border}; font-weight: 600;
    }}

    #kindBadge {{
        background: {c.accent_soft}; color: {c.accent_strong}; border-radius: 8px;
        padding: 2px 9px; font-size: 9pt; font-weight: 700;
    }}
    #hitTitle {{ font-size: 11pt; font-weight: 600; color: {c.text}; }}
    #hitSnippet {{ color: {c.muted}; }}
    #chipClose {{ border: none; background: transparent; color: {c.muted}; padding: 0 4px; }}
    #chipClose:hover {{ color: {c.danger}; }}
    /* A kept search phrase: the accent's tint, so it never reads as one of the tags. */
    #phraseChip {{
        background: {c.accent_soft}; border: 1px solid {c.accent}; border-radius: 11px;
    }}
    #phraseChip QLabel {{ color: {on_soft}; font-weight: 600; }}
    /* An on/off switch that says what it does: quiet when off, filled when on. */
    QToolButton#toggleChip {{
        background: transparent; color: {c.muted}; border: 1px solid {c.border};
        border-radius: 12px; padding: 6px 10px; font-weight: 600;
    }}
    QToolButton#toggleChip:hover {{ color: {c.text}; background: {c.hover}; }}
    QToolButton#toggleChip:checked {{
        background: {c.accent_soft}; color: {on_soft}; border-color: {c.accent};
    }}
    QToolButton#toggleChip:focus {{ border: 1px dashed {c.accent_strong}; }}
    #hint {{ color: {c.muted}; font-size: 8.5pt; padding: 0 4px; }}
    /* Keycaps (widgets/key_hint.py): quiet enough to sit beside every main control. */
    QLabel#keyHint {{
        color: {c.muted}; background: transparent; border: 1px solid {c.border};
        border-bottom-width: 2px; border-radius: 5px; padding: 0 5px;
        font-size: 8pt; font-weight: 500;
    }}
    QPushButton#linkButton {{
        background: transparent; border: none; color: {c.accent_strong};
        padding: 2px 4px; font-weight: 600;
    }}
    QPushButton#linkButton:hover {{ text-decoration: underline; }}

    #sectionTitle {{ font-size: 12.5pt; font-weight: 700; color: {c.text}; }}
    #clock {{ font-size: 12pt; font-weight: 600; color: {c.text}; min-width: 64px; }}
    QPushButton#playButton {{
        background: {c.accent}; border: 2px solid {c.accent}; border-radius: 24px; padding: 0;
    }}
    QPushButton#playButton:hover {{ border-color: {c.accent_strong}; }}
    QPushButton#playButton:focus {{ border: 2px solid {c.accent_strong}; padding: 0; }}
    QPushButton#playButton:disabled {{ background: {c.hover}; border-color: {c.hover}; }}
    QPushButton#transportButton {{
        background: transparent; border: 2px solid transparent; border-radius: 20px; padding: 0;
    }}
    QPushButton#transportButton:hover {{ background: {c.hover}; }}
    QPushButton#transportButton:focus {{ border: 2px solid {c.accent_strong}; padding: 0; }}
    QToolButton#speedButton {{
        background: {c.panel}; color: {c.text}; border: 1px solid {c.border};
        border-radius: 10px; padding: 5px 11px; min-width: 44px; font-weight: 600;
    }}
    QToolButton#speedButton:hover {{ background: {c.hover}; border-color: {c.accent}; }}
    QToolButton#speedButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#silenceButton {{
        background: {c.panel}; color: {c.text}; border: 1px solid {c.border};
        border-radius: 10px; padding: 5px 10px; font-weight: 600;
    }}
    QToolButton#silenceButton:hover {{ background: {c.hover}; border-color: {c.accent}; }}
    QToolButton#silenceButton:focus {{ border-color: {c.accent_strong}; }}
    QToolButton#silenceButton[active="true"] {{
        background: {c.accent}; color: {c.accent_text}; border-color: {c.accent};
    }}
    QToolButton#silenceButton[active="true"]:hover {{ border-color: {c.accent_strong}; }}
    QToolButton#silenceButton:disabled {{ color: {c.muted}; }}
    #silencePopup {{ background: {c.surface}; border: 1px solid {c.border}; }}
    #silenceValue {{ color: {c.text}; font-weight: 700; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c.accent_strong}; border-radius: 2px; }}
    QSlider::add-page:horizontal {{ background: {c.border}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c.surface}; border: 2px solid {c.accent_strong};
        width: 12px; height: 12px; margin: -6px 0; border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {c.accent_soft}; }}

    #noteScroll, #noteHost {{ background: transparent; }}
    #noteRow {{ background: transparent; border-radius: 10px; border: 2px solid transparent; }}
    #noteRow:hover {{ background: {c.hover}; }}
    #noteRow[active="true"] {{ background: {c.accent_soft}; }}
    #noteRow:focus {{ border: 2px solid {c.accent_strong}; }}
    #noteText {{ color: {c.text}; font-size: 10.5pt; }}
    QToolButton#gotoButton {{
        background: {c.panel}; color: {c.muted}; border: 1px solid {c.border};
        border-radius: 8px; padding: 3px 9px; font-weight: 600;
    }}
    QToolButton#gotoButton:hover {{ color: {c.text}; border-color: {c.accent}; }}
    #noteRow[active="true"] QToolButton#gotoButton {{
        background: {c.accent}; color: {c.accent_text}; border-color: {c.accent};
    }}
    QToolButton#captureChip {{
        background: {c.panel}; color: {c.muted}; border: 1px solid {c.border};
        border-radius: 10px; padding: 7px 11px; min-width: 52px; font-weight: 600;
    }}
    QToolButton#captureChip[captured="true"] {{
        background: {c.accent}; color: {c.accent_text}; border-color: {c.accent};
    }}

    #fieldLabel {{ color: {c.muted}; font-size: 9.5pt; font-weight: 600; }}
    QPushButton#flatButton {{
        background: transparent; border: 1px solid transparent; color: {c.accent_strong};
        padding: 5px 11px; font-weight: 600;
    }}
    QPushButton#flatButton:hover {{ background: {c.accent_soft}; }}
    QPushButton#flatButton:focus {{ border: 2px solid {c.accent_strong}; padding: 4px 10px; }}
    QPushButton#recordButton {{ color: {c.danger}; font-weight: 700; }}
    QPushButton#recordButton:hover {{ background: {c.danger_soft}; border-color: {c.danger}; }}
    QToolButton#backButton {{
        background: transparent; color: {c.muted}; border: 2px solid transparent;
        border-radius: 10px; padding: 6px 10px;
    }}
    QToolButton#backButton:hover {{ background: {c.hover}; color: {c.text}; }}
    QToolButton#backButton:focus {{ border-color: {c.accent_strong}; }}
    #staleBadge {{
        color: {c.warning}; background: {c.warning_soft}; border-radius: 10px;
        padding: 3px 11px; font-size: 9pt; font-weight: 700;
    }}
    #sidePanel {{ background: {c.panel}; border: 1px solid {c.border}; border-radius: 16px; }}
    #sidePanel QListWidget {{ background: {c.surface}; }}
    /* The note title is a heading you can type in, not a form field: the tab above
       already shows it, so a boxed input would read as a duplicate. */
    QLineEdit#noteTitle {{
        font-size: 13.5pt; font-weight: 700; background: transparent; border: none;
        border-bottom: 1px solid transparent; border-radius: 0; padding: 4px 2px;
    }}
    QLineEdit#noteTitle:hover {{ border-bottom: 1px solid {c.border}; }}
    QLineEdit#noteTitle:focus {{
        border-bottom: 2px solid {c.accent_strong}; padding: 4px 2px 3px;
    }}
    QPlainTextEdit#noteBody {{ font-size: 11.5pt; padding: 14px; }}
    QPlainTextEdit#noteBody:focus {{ padding: 13px; }}

    /* Tabs are pills: the chosen one is filled, the rest are quiet labels. */
    QTabBar#noteTabs::tab, QTabBar#panelTabs::tab {{
        background: transparent; color: {c.muted}; padding: 6px 14px; margin: 2px;
        border: 1px solid transparent; border-radius: 10px;
    }}
    QTabBar#noteTabs::tab {{ max-width: 220px; }}
    QTabBar#panelTabs::tab {{ padding: 6px 8px; }}
    QTabBar#noteTabs::tab:hover, QTabBar#panelTabs::tab:hover {{
        color: {c.text}; background: {c.hover};
    }}
    QTabBar#noteTabs::tab:selected, QTabBar#panelTabs::tab:selected {{
        color: {on_soft}; font-weight: 700; background: {c.accent_soft};
        border-color: {c.accent};
    }}
    QTabBar#noteTabs:focus, QTabBar#panelTabs:focus {{ border: 1px dashed {c.accent_strong}; }}
    /* Any other tab widget (settings) gets the same pills over a hairline. */
    QTabWidget::pane {{ border: none; border-top: 1px solid {c.border}; padding-top: 10px; }}
    QTabBar::tab {{
        background: transparent; color: {c.muted}; padding: 7px 16px; margin: 0 2px 6px;
        border: 1px solid transparent; border-radius: 10px;
    }}
    QTabBar::tab:hover {{ background: {c.hover}; color: {c.text}; }}
    QTabBar::tab:selected {{
        background: {c.accent_soft}; color: {on_soft}; border-color: {c.accent};
        font-weight: 700;
    }}

    #boardFrame {{ background: {c.panel}; border-radius: 16px; }}
    #columnTitle {{ font-weight: 700; color: {c.text}; }}
    #statusDot {{
        border-radius: 5px; min-width: 10px; max-width: 10px;
        min-height: 10px; max-height: 10px;
    }}
    QListWidget#boardColumn {{ background: transparent; border: none; padding: 0; }}
    QListWidget#boardColumn::item, QListWidget#boardColumn::item:selected,
    QListWidget#boardColumn::item:hover {{ background: transparent; color: {c.text}; }}
    QListWidget#boardColumn:focus {{ border: none; }}
    #boardScroll, #boardHost {{ background: transparent; }}

    #resumeCard {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 22px; }}
    #eyebrow {{ color: {c.accent_strong}; font-weight: 700; font-size: 10pt; }}
    #resumeTitle {{ font-size: 21pt; font-weight: 700; color: {c.text}; }}
    #resumeNext {{ font-size: 13pt; color: {c.text}; }}
    #resumeNoteTitle {{ font-size: 11pt; font-weight: 600; color: {c.text}; }}

    #inboxFrame {{
        background: {c.surface}; border: 2px solid {c.accent}; border-radius: 18px;
    }}
    QPlainTextEdit#inboxText {{ font-size: 12.5pt; }}

    QToolTip {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border}; padding: 6px 8px;
    }}
    QMenu {{
        background: {c.surface}; color: {c.text}; border: 1px solid {c.border}; padding: 5px;
    }}
    QMenu::item {{ padding: 7px 18px; border-radius: 7px; }}
    QMenu::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
    QMenu::separator {{ height: 1px; background: {c.border}; margin: 4px 8px; }}
    QProgressBar {{
        background: {c.panel}; border: 1px solid {c.border}; border-radius: 7px;
        text-align: center; color: {c.text}; min-height: 14px;
    }}
    QProgressBar::chunk {{ background: {c.accent}; border-radius: 6px; }}

    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 3px 1px;
    }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 1px 3px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c.border}; border-radius: 4px; min-height: 32px; min-width: 32px;
    }}
    QScrollBar::handle:hover {{ background: {c.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    #divider {{ background: {c.border}; max-height: 1px; min-height: 1px; border: none; }}
    #panelTitle {{ font-size: 10.5pt; font-weight: 700; color: {c.text}; }}
    #countPill {{
        background: {c.accent_soft}; color: {c.accent_strong};
        border-radius: 9px; padding: 1px 8px; font-size: 9pt; font-weight: 700; min-width: 10px;
    }}
    #miniList {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 12px; padding: 4px;
    }}
    #miniList::item {{ padding: 7px 9px; border-radius: 8px; }}
    #miniList::item:hover {{ background: {c.hover}; }}
    #miniList::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
    #miniList:focus {{ border: 1px solid {c.accent_strong}; }}
    #card {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 16px;
    }}

    /* Toast: floats over the page, reads as a raised surface in both themes. */
    #toast {{
        background: {c.surface}; border: 1px solid {c.accent}; border-radius: 14px;
    }}
    #toastText {{ color: {c.text}; }}
    QPushButton#toastAction {{
        background: {c.accent_soft}; color: {c.accent_strong}; border: 1px solid transparent;
        border-radius: 9px; padding: 5px 12px; font-weight: 700;
    }}
    QPushButton#toastAction:hover {{ background: {c.accent}; color: {c.accent_text}; }}
    QToolButton#toastClose {{
        background: transparent; border: none; color: {c.muted};
        padding: 0 6px; font-size: 13pt;
    }}
    QToolButton#toastClose:hover {{ color: {c.text}; }}
    {_tinted_rules(dark)}
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
        global _dark
        self._theme = theme or self._theme
        _dark = self._theme is Theme.DARK
        c = colors()
        self._app.setPalette(_palette(c))
        rtl = self._app.layoutDirection() == Qt.LayoutDirection.RightToLeft
        self._app.setStyleSheet(_stylesheet(c, _dark, rtl))
        for window in self._app.topLevelWidgets():
            set_native_dark_title_bar(window, _dark)
        self.changed.emit(self._theme)

    def toggle(self) -> None:
        new = Theme.LIGHT if self._theme is Theme.DARK else Theme.DARK
        self._settings.set_theme(new)
        self.apply(new)
