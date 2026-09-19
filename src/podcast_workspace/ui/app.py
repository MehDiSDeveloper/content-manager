"""Application entry point."""

import sys

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from podcast_workspace import __version__
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.main_window import MainWindow
from podcast_workspace.ui.theme import ThemeManager, load_fonts


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PodcastWorkspace")
    app.setApplicationDisplayName(strings.APP_NAME)
    app.setApplicationVersion(__version__)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    QLocale.setDefault(QLocale(QLocale.Language.Persian, QLocale.Country.Iran))
    load_fonts(app)

    try:
        workspace = Workspace.open()
    except Exception as exc:  # startup must fail visibly, not silently
        QMessageBox.critical(
            None, strings.STARTUP_ERROR_TITLE, strings.STARTUP_ERROR_BODY.format(error=exc)
        )
        return 1

    try:
        theme = ThemeManager(app, workspace.settings)
        theme.apply()
        window = MainWindow(workspace, theme)
        window.show()
        return app.exec()
    finally:
        workspace.close()


if __name__ == "__main__":
    sys.exit(main())
