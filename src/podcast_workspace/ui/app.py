"""Application entry point."""

import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMessageBox

from podcast_workspace import __version__
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import language, strings
from podcast_workspace.ui.main_window import MainWindow
from podcast_workspace.ui.theme import ThemeManager, load_fonts


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PodcastWorkspace")
    app.setApplicationVersion(__version__)
    load_fonts(app)

    try:
        workspace = Workspace.open()
    except Exception as exc:  # startup must fail visibly, not silently
        QMessageBox.critical(
            None, strings.STARTUP_ERROR_TITLE, strings.STARTUP_ERROR_BODY.format(error=exc)
        )
        return 1

    restart = False
    try:
        theme = ThemeManager(app, workspace.settings)
        chosen = workspace.settings.language()
        if chosen is None:
            # First start: ask once, in both languages, and remember the answer.
            theme.apply()
            dialog = language.LanguageDialog(language.system_language())
            dialog.exec()
            chosen = dialog.choice
            workspace.settings.set_language(chosen)
        language.apply(app, chosen)
        theme.apply()  # again: the stylesheet depends on the direction just set
        window = MainWindow(workspace, theme)
        window.show()
        code = app.exec()
        restart = window.restart_requested
    finally:
        workspace.close()
    if restart:
        program, args = language.restart_command()
        QProcess.startDetached(program, args)
    return code


if __name__ == "__main__":
    sys.exit(main())
