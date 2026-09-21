"""The UI language: chosen once on first start, remembered, changed from Settings.

The whole UI reads its text from `strings` while it is being built, so a language takes
effect at startup (`apply`) and switching it means starting again (`restart_command`).
"""

import sys

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from podcast_workspace.services.settings_service import Language
from podcast_workspace.ui import strings

# Shown before any language exists, so it has to speak both.
_CHOOSE_TITLE = "Podcast Workspace · فضای کاری پادکست"
_CHOOSE_PROMPT = "زبان برنامه را انتخاب کنید\nChoose the app language"
_CHOOSE_HINT = "بعداً از تنظیمات عوض می‌شود · You can change it later in Settings"


def system_language() -> Language:
    """A sensible first guess: Persian on a Persian system, English everywhere else."""
    return Language.FA if QLocale.system().language() == QLocale.Language.Persian else Language.EN


def apply(app: QApplication, language: Language) -> None:
    """Load the language's text and set the direction and locale that go with it."""
    strings.apply_language(language.value)
    if language is Language.FA:
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        QLocale.setDefault(QLocale(QLocale.Language.Persian, QLocale.Country.Iran))
    else:
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app.setApplicationDisplayName(strings.APP_NAME)


class LanguageDialog(QDialog):
    """First start: two big buttons, one per language. Closing it picks the guess."""

    def __init__(self, suggested: Language) -> None:
        super().__init__()
        self.choice = suggested
        self.setWindowTitle(_CHOOSE_TITLE)
        self.setMinimumWidth(460)
        col = QVBoxLayout(self)
        col.setContentsMargins(32, 28, 32, 24)
        col.setSpacing(16)
        prompt = QLabel(_CHOOSE_PROMPT, objectName="dialogTitle")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(prompt)
        row = QHBoxLayout()
        row.setSpacing(12)
        for language in (Language.FA, Language.EN):
            button = QPushButton(strings.LANGUAGE_NAMES[language.value])
            button.setObjectName("primary" if language is suggested else "")
            button.setMinimumHeight(52)
            button.clicked.connect(lambda _c=False, lang=language: self._choose(lang))
            row.addWidget(button, 1)
            if language is suggested:
                button.setDefault(True)
                button.setFocus()
        col.addLayout(row)
        hint = QLabel(_CHOOSE_HINT, objectName="muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(hint)

    def _choose(self, language: Language) -> None:
        self.choice = language
        self.accept()


def restart_command() -> tuple[str, list[str]]:
    """How to start this app again, the way it was started this time."""
    args = sys.argv[1:]
    if getattr(sys, "frozen", False):  # a packaged build: the executable is the app
        return sys.executable, args
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    if spec is not None and spec.name:  # python -m podcast_workspace
        return sys.executable, ["-m", spec.name.removesuffix(".__main__"), *args]
    launcher = sys.argv[0] if sys.argv else ""
    if launcher.lower().endswith(".exe"):  # the installed podcast-workspace.exe
        return launcher, args
    return sys.executable, [launcher, *args]
