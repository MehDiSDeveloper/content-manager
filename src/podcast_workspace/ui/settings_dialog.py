"""Settings, in four tabs: general (language, recorder, hotkey), Bale bot, transcription,
data (export/import, backup reminder).

One instance lives for the whole session (MainWindow keeps it), so a model download or an
export started here can finish safely after the dialog is closed.
"""

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.paths import data_dir
from podcast_workspace.services.backup import ExportFormatError, ExportReport, RestoreReport
from podcast_workspace.services.bale_bot import BaleBotService, BotStatus, TokenCheck
from podcast_workspace.services.settings_service import Language
from podcast_workspace.services.transcription import WHISPER_MODELS, whisper_installed
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.bot_controller import BotController
from podcast_workspace.ui.support import (
    confirm,
    describe_error,
    format_datetime,
    local_digits,
    run_async,
    run_detached,
    show_error,
)

TAB_GENERAL, TAB_BOT, TAB_TRANSCRIPTION, TAB_DATA = range(4)
DOWNLOAD_POLL_MS = 1000


def _muted(text: str = "") -> QLabel:
    label = QLabel(text, objectName="muted")
    label.setWordWrap(True)
    return label


def _folder_size(path: Path) -> int:
    total = 0
    if path.exists():
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    return total


class SettingsDialog(QDialog):
    data_replaced = Signal(object)  # RestoreReport
    restart_requested = Signal()  # the language changed and the user chose to restart now
    _task_progress = Signal(float)

    def __init__(
        self,
        parent: QWidget,
        workspace: Workspace,
        bot: BotController,
        hotkey_label: str,
    ) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._bot = bot
        self._hotkey_label = hotkey_label
        self._downloading: str | None = None
        self._progress_dialog: QProgressDialog | None = None
        self.setWindowTitle(strings.SETTINGS)
        self.setMinimumWidth(620)

        col = QVBoxLayout(self)
        col.setContentsMargins(24, 22, 24, 20)
        col.setSpacing(12)
        col.addWidget(QLabel(strings.SETTINGS, objectName="dialogTitle"))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._general_tab(), strings.SETTINGS_TAB_GENERAL)
        self.tabs.addTab(self._bot_tab(), strings.SETTINGS_TAB_BOT)
        self.tabs.addTab(self._transcription_tab(), strings.SETTINGS_TAB_TRANSCRIPTION)
        self.tabs.addTab(self._data_tab(), strings.SETTINGS_TAB_DATA)
        col.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox()
        save = buttons.addButton(strings.SAVE, QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("primary")
        save.setDefault(True)
        buttons.addButton(strings.CANCEL, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

        bot.status_changed.connect(self._show_bot_status)
        self._task_progress.connect(self._on_task_progress)
        self._download_timer = QTimer(self, interval=DOWNLOAD_POLL_MS)
        self._download_timer.timeout.connect(self._poll_download)

    # tabs ------------------------------------------------------------------------------
    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(4, 16, 4, 8)
        col.setSpacing(8)
        return page, col

    def _general_tab(self) -> QWidget:
        page, col = self._page()
        col.addWidget(QLabel(strings.SETTINGS_LANGUAGE, objectName="fieldLabel"))
        self.language_box = QComboBox()
        for language in Language:
            self.language_box.addItem(strings.LANGUAGE_NAMES[language.value], language)
        col.addWidget(self.language_box, 0, Qt.AlignmentFlag.AlignLeading)
        col.addSpacing(12)
        col.addWidget(QLabel(strings.SETTINGS_RECORDER, objectName="fieldLabel"))
        # Shown only when «Record» brought the user here: says why settings opened.
        self.recorder_needed = QLabel(strings.SETTINGS_RECORDER_NEEDED, objectName="warning")
        self.recorder_needed.setWordWrap(True)
        self.recorder_needed.hide()
        col.addWidget(self.recorder_needed)
        row = QHBoxLayout()
        self.recorder = QLineEdit()
        self.recorder.setPlaceholderText(r"C:\Program Files\Audacity\Audacity.exe")
        row.addWidget(self.recorder, 1)
        browse = QPushButton(strings.SETTINGS_BROWSE)
        browse.clicked.connect(self._browse_recorder)
        row.addWidget(browse)
        col.addLayout(row)
        col.addWidget(_muted(strings.SETTINGS_RECORDER_HINT))
        col.addSpacing(12)
        col.addWidget(QLabel(strings.SETTINGS_HOTKEY, objectName="fieldLabel"))
        self.hotkey_status = _muted()
        col.addWidget(self.hotkey_status)
        col.addStretch(1)
        return page

    def _bot_tab(self) -> QWidget:
        page, col = self._page()
        self.bot_enabled = QCheckBox(strings.BOT_ENABLE)
        col.addWidget(self.bot_enabled)
        col.addSpacing(6)
        col.addWidget(QLabel(strings.BOT_TOKEN, objectName="fieldLabel"))
        row = QHBoxLayout()
        self.token = QLineEdit()
        self.token.setPlaceholderText(strings.BOT_TOKEN_PLACEHOLDER)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row.addWidget(self.token, 1)
        show = QPushButton(strings.BOT_TOKEN_SHOW)
        show.setCheckable(True)
        show.toggled.connect(
            lambda on: self.token.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row.addWidget(show)
        self.check_button = QPushButton(strings.BOT_TOKEN_CHECK)
        self.check_button.clicked.connect(self._check_token)
        row.addWidget(self.check_button)
        col.addLayout(row)
        self.token_result = _muted()
        col.addWidget(self.token_result)
        self.bot_status = _muted()
        col.addWidget(self.bot_status)
        owner_row = QHBoxLayout()
        self.owner = _muted()
        owner_row.addWidget(self.owner, 1)
        self.owner_reset = QPushButton(strings.BOT_OWNER_RESET, objectName="flatButton")
        self.owner_reset.clicked.connect(self._reset_owner)
        owner_row.addWidget(self.owner_reset)
        col.addLayout(owner_row)
        col.addSpacing(8)
        col.addWidget(_muted(strings.BOT_HELP))
        col.addStretch(1)
        return page

    def _transcription_tab(self) -> QWidget:
        page, col = self._page()
        self.whisper_missing = QLabel(strings.TR_NOT_INSTALLED, objectName="warning")
        self.whisper_missing.setWordWrap(True)
        col.addWidget(self.whisper_missing)
        col.addWidget(QLabel(strings.TR_MODEL, objectName="fieldLabel"))
        row = QHBoxLayout()
        self.model_box = QComboBox()
        for name in WHISPER_MODELS:
            self.model_box.addItem(strings.TR_MODELS.get(name, name), name)
        self.model_box.currentIndexChanged.connect(lambda _i: self._show_model_state())
        row.addWidget(self.model_box, 1)
        self.download_button = QPushButton(strings.TR_MODEL_DOWNLOAD)
        self.download_button.clicked.connect(self._download_model)
        row.addWidget(self.download_button)
        col.addLayout(row)
        self.model_state = _muted()
        self.model_state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.model_state)
        col.addSpacing(8)
        col.addWidget(QLabel(strings.TR_MODEL_DIR, objectName="fieldLabel"))
        dir_row = QHBoxLayout()
        self.model_dir = QLineEdit()
        self.model_dir.setPlaceholderText(strings.TR_MODEL_DIR_PLACEHOLDER)
        self.model_dir.textChanged.connect(lambda _t: self._show_model_state())
        dir_row.addWidget(self.model_dir, 1)
        browse = QPushButton(strings.SETTINGS_BROWSE)
        browse.clicked.connect(self._browse_model_dir)
        dir_row.addWidget(browse)
        col.addLayout(dir_row)
        col.addSpacing(8)
        col.addWidget(_muted(strings.TR_MODEL_HELP))
        col.addStretch(1)
        return page

    def _data_tab(self) -> QWidget:
        page, col = self._page()
        export = QPushButton(strings.DATA_EXPORT)
        export.clicked.connect(self._export)
        col.addWidget(export, 0, Qt.AlignmentFlag.AlignLeading)
        col.addWidget(_muted(strings.DATA_EXPORT_HELP))
        col.addSpacing(12)
        restore = QPushButton(strings.DATA_IMPORT)
        restore.clicked.connect(self._import)
        col.addWidget(restore, 0, Qt.AlignmentFlag.AlignLeading)
        col.addWidget(_muted(strings.DATA_IMPORT_HELP))
        col.addSpacing(12)
        col.addWidget(QLabel(strings.DATA_FOLDER, objectName="fieldLabel"))
        row = QHBoxLayout()
        path = _muted(str(data_dir()))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row.addWidget(path, 1)
        open_folder = QPushButton(strings.DATA_OPEN_FOLDER)
        open_folder.clicked.connect(lambda: os.startfile(data_dir()))
        row.addWidget(open_folder)
        col.addLayout(row)
        col.addSpacing(12)
        col.addWidget(QLabel(strings.SETTINGS_BACKUP_REMINDER, objectName="fieldLabel"))
        self.reminder_box = QComboBox()
        for days, label in strings.BACKUP_INTERVALS.items():
            self.reminder_box.addItem(label, days)
        col.addWidget(self.reminder_box, 0, Qt.AlignmentFlag.AlignLeading)
        self.last_backup = _muted()
        col.addWidget(self.last_backup)
        self.data_status = _muted()
        self.data_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.data_status)
        col.addStretch(1)
        return page

    # open ------------------------------------------------------------------------------
    def open_at(
        self, tab: int, hotkey_ok: bool, export: bool = False, ask_recorder: bool = False
    ) -> bool:
        """Reload every field from settings, show the tab, run modally.

        `export` starts an export as soon as the dialog is up (the backup reminder's
        "Back up now"), so its progress and its result show where they always do.
        `ask_recorder`: «Record» was pressed with no program set — say so, and put the
        caret in that field.
        """
        settings = self._ws.settings
        current = settings.language() or Language.FA
        self.language_box.setCurrentIndex(max(0, self.language_box.findData(current)))
        interval = settings.backup_interval_days()
        index = self.reminder_box.findData(interval)
        if index < 0:  # a value set some other way: show it rather than lose it
            self.reminder_box.addItem(local_digits(interval), interval)
            index = self.reminder_box.count() - 1
        self.reminder_box.setCurrentIndex(index)
        self._show_last_backup()
        self.recorder.setText(settings.recorder_path())
        template = strings.SETTINGS_HOTKEY_OK if hotkey_ok else strings.SETTINGS_HOTKEY_FAIL
        # The line opens with Latin keys: the mark keeps it in the UI's direction.
        self.hotkey_status.setText(
            strings.DIRECTION_MARK + template.format(keys=self._hotkey_label)
        )
        self.hotkey_status.setObjectName("muted" if hotkey_ok else "warning")
        self.hotkey_status.style().polish(self.hotkey_status)
        self.bot_enabled.setChecked(settings.bale_enabled())
        self.token.setText(settings.bale_token())
        self.token_result.setText("")
        self._show_owner()
        self._show_bot_status(self._bot.status, "")
        self.whisper_missing.setVisible(not whisper_installed())
        index = self.model_box.findData(settings.whisper_model())
        self.model_box.setCurrentIndex(max(0, index))
        self.model_dir.setText(settings.whisper_model_dir())
        self._show_model_state()
        self.data_status.setText("")
        self.tabs.setCurrentIndex(TAB_GENERAL if ask_recorder else tab)
        self.recorder_needed.setVisible(ask_recorder)
        if ask_recorder:
            self.recorder.setFocus()
        if export:
            QTimer.singleShot(0, self._export)
        return self.exec() == QDialog.DialogCode.Accepted

    def _show_last_backup(self) -> None:
        last = self._ws.settings.last_backup_at()
        self.last_backup.setText(
            strings.BACKUP_LAST.format(when=format_datetime(last))
            if last is not None
            else strings.BACKUP_LAST_NEVER
        )

    def accept(self) -> None:
        settings = self._ws.settings
        settings.set_backup_interval_days(int(self.reminder_box.currentData()))
        settings.set_recorder_path(self.recorder.text())
        settings.set_whisper_model(str(self.model_box.currentData()))
        settings.set_whisper_model_dir(self.model_dir.text())
        bot_changed = (
            self.token.text().strip() != settings.bale_token()
            or self.bot_enabled.isChecked() != settings.bale_enabled()
        )
        settings.set_bale_token(self.token.text())
        settings.set_bale_enabled(self.bot_enabled.isChecked())
        if bot_changed or self._bot.status in (BotStatus.STOPPED, BotStatus.UNAUTHORIZED):
            self._bot.restart()
        language = Language(self.language_box.currentData())
        changed = language is not (settings.language() or Language.FA)
        settings.set_language(language)
        super().accept()
        if changed and self._ask_restart():
            self.restart_requested.emit()

    def _ask_restart(self) -> bool:
        """The whole UI is built in one language; the new one needs a fresh start."""
        box = QMessageBox(self.parentWidget())
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(strings.LANGUAGE_RESTART_TITLE)
        box.setText(strings.LANGUAGE_RESTART)
        now = box.addButton(strings.LANGUAGE_RESTART_NOW, QMessageBox.ButtonRole.AcceptRole)
        now.setObjectName("primary")
        box.addButton(strings.LANGUAGE_RESTART_LATER, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(now)
        box.exec()
        return box.clickedButton() is now

    # general ---------------------------------------------------------------------------
    def _browse_recorder(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            strings.SETTINGS_PROGRAM_DIALOG,
            self.recorder.text(),
            strings.SETTINGS_PROGRAM_FILTER,
        )
        if path:
            self.recorder.setText(path.replace("/", "\\"))

    # bot -------------------------------------------------------------------------------
    def _show_bot_status(self, status: BotStatus, _detail: str) -> None:
        text = strings.BOT_STATUS.get(status.value, status.value)
        self.bot_status.setText(strings.BOT_SIDEBAR.format(status=text))

    def _show_owner(self) -> None:
        owner = self._ws.settings.bale_owner()
        self.owner.setText(
            strings.BOT_OWNER.format(name=owner.name) if owner else strings.BOT_OWNER_NONE
        )
        self.owner_reset.setVisible(owner is not None)

    def _reset_owner(self) -> None:
        self._ws.settings.set_bale_owner(None)
        self._show_owner()

    def _check_token(self) -> None:
        token = self.token.text().strip()
        if not token:
            return
        self.check_button.setEnabled(False)
        self.token_result.setText(strings.BOT_TOKEN_CHECKING)
        run_async(
            lambda: BaleBotService.check_token(token),
            self._on_token_ok,
            self._on_token_failed,
        )

    def _on_token_ok(self, check: TokenCheck) -> None:
        self.check_button.setEnabled(True)
        match check.status:
            case BotStatus.UNAUTHORIZED:
                text = strings.BOT_TOKEN_BAD
            case BotStatus.OFFLINE:
                text = strings.BOT_TOKEN_OFFLINE
            case _:
                text = strings.BOT_TOKEN_OK.format(name=check.bot_name)
        self.token_result.setText(text)

    def _on_token_failed(self, exc: BaseException) -> None:
        self.check_button.setEnabled(True)
        self.token_result.setText(describe_error(exc))

    # transcription ---------------------------------------------------------------------
    def _show_model_state(self) -> None:
        name = str(self.model_box.currentData())
        custom = self.model_dir.text().strip()
        transcripts = self._ws.transcripts
        if self._downloading is not None:
            self.download_button.setEnabled(False)
            return
        downloaded = transcripts.is_downloaded(name)
        self.download_button.setVisible(not custom)
        self.download_button.setEnabled(whisper_installed() and not downloaded)
        if custom:
            ready = (Path(custom) / "model.bin").is_file()
            self.model_state.setText(
                strings.TR_MODEL_READY.format(path=custom) if ready else strings.TR_MODEL_NOT_READY
            )
        elif downloaded:
            path = transcripts.managed_model_dir(name)
            self.model_state.setText(strings.TR_MODEL_READY.format(path=path))
        else:
            self.model_state.setText(strings.TR_MODEL_NOT_READY)

    def _browse_model_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, strings.TR_MODEL_DIR_DIALOG, self.model_dir.text()
        )
        if path:
            self.model_dir.setText(path.replace("/", "\\"))

    def _download_model(self) -> None:
        name = str(self.model_box.currentData())
        self._downloading = name
        self.download_button.setEnabled(False)
        self.model_box.setEnabled(False)
        self.model_state.setText(strings.TR_MODEL_DOWNLOADING)
        self._download_timer.start()
        run_detached(
            lambda: self._ws.transcripts.download_model(name),
            lambda _path: self._download_finished(None),
            self._download_finished,
        )

    def _poll_download(self) -> None:
        if self._downloading is None:
            return
        size = _folder_size(self._ws.transcripts.managed_model_dir(self._downloading))
        mb = local_digits(size // (1024 * 1024))
        self.model_state.setText(f"{strings.TR_MODEL_DOWNLOADING}  {mb} MB")

    def _download_finished(self, exc: BaseException | None) -> None:
        self._downloading = None
        self._download_timer.stop()
        self.model_box.setEnabled(True)
        self._show_model_state()
        if exc is not None:
            self.model_state.setText(
                strings.TR_MODEL_DOWNLOAD_FAILED.format(error=describe_error(exc))
            )

    # data ------------------------------------------------------------------------------
    def _start_task(self, label: str) -> None:
        dialog = QProgressDialog(label.format(percent=local_digits(0)), "", 0, 1000, self)
        dialog.setWindowTitle(strings.SETTINGS_TAB_DATA)
        dialog.setCancelButton(None)  # type: ignore[arg-type]
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setProperty("template", label)
        dialog.setValue(0)
        self._progress_dialog = dialog

    def _on_task_progress(self, fraction: float) -> None:
        dialog = self._progress_dialog
        if dialog is not None:
            dialog.setValue(int(fraction * 1000))
            dialog.setLabelText(
                str(dialog.property("template")).format(percent=local_digits(int(fraction * 100)))
            )

    def _end_task(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    def _export(self) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d")
        suggested = Path.home() / "Documents" / f"podcast-workspace_{stamp}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, strings.DATA_EXPORT_DIALOG, str(suggested), strings.DATA_EXPORT_FILTER
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        self._flush_pages()
        self._start_task(strings.DATA_EXPORTING)
        emit = self._task_progress.emit
        run_async(
            lambda: self._ws.backup.export(target, emit),
            self._export_done,
            self._task_failed,
        )

    def _export_done(self, report: ExportReport) -> None:
        self._end_task()
        self._show_last_backup()
        lines = [strings.DATA_EXPORT_DONE.format(path=report.path)]
        if report.missing_audio:
            lines.append(
                strings.DATA_EXPORT_MISSING.format(n=local_digits(len(report.missing_audio)))
            )
        self.data_status.setText("\n".join(lines))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, strings.DATA_IMPORT_DIALOG, str(Path.home()), strings.DATA_EXPORT_FILTER
        )
        if not path or not confirm(self, strings.DATA_IMPORT_CONFIRM, strings.DATA_IMPORT_ACTION):
            return
        self._flush_pages()
        self._start_task(strings.DATA_IMPORTING)
        emit = self._task_progress.emit
        source = Path(path)
        run_async(
            lambda: self._ws.backup.restore(source, emit),
            self._import_done,
            self._task_failed,
        )

    def _import_done(self, report: RestoreReport) -> None:
        self._end_task()
        counts = {k: local_digits(v) for k, v in report.counts.items()}
        lines = [
            strings.DATA_IMPORT_DONE.format(
                episodes=counts["episodes"],
                voices=counts["voices"],
                ideas=counts["ideas"],
                tags=counts["tags"],
            )
        ]
        if report.missing_audio:
            lines.append(
                strings.DATA_EXPORT_MISSING.format(n=local_digits(len(report.missing_audio)))
            )
        self.data_status.setText("\n".join(lines))
        self.data_replaced.emit(report)

    def _task_failed(self, exc: BaseException) -> None:
        self._end_task()
        if isinstance(exc, ExportFormatError):
            QMessageBox.warning(self, strings.ERROR_TITLE, strings.DATA_IMPORT_BAD_FILE)
        else:
            show_error(self, exc)

    def _flush_pages(self) -> None:
        parent = self.parent()
        flush = getattr(parent, "flush_pages", None)
        if callable(flush):
            flush()
