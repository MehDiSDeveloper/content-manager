"""Application entry point."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMessageBox

from podcast_workspace import __version__
from podcast_workspace.paths import log_path
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import language, strings
from podcast_workspace.ui.main_window import MainWindow
from podcast_workspace.ui.theme import ThemeManager, configure_text_rendering, load_fonts


def _setup_logging() -> None:
    """pythonw has no console: warnings and crashes (any thread) go to app.log instead."""
    try:
        handler = RotatingFileHandler(
            log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    log = logging.getLogger("podcast_workspace")
    sys.excepthook = lambda *exc: log.critical("uncaught", exc_info=exc)
    threading.excepthook = lambda args: log.critical(
        "uncaught in thread %s",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def main() -> int:
    _setup_logging()
    configure_text_rendering()
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
