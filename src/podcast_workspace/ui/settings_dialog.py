"""Settings: path of the external recording program; status of the global idea hotkey."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.ui import strings


class SettingsDialog(QDialog):
    def __init__(
        self, parent: QWidget, settings: SettingsService, hotkey_label: str, hotkey_ok: bool
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(strings.SETTINGS)
        self.setMinimumWidth(560)
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 22, 24, 20)
        col.setSpacing(10)
        col.addWidget(QLabel(strings.SETTINGS, objectName="dialogTitle"))
        col.addSpacing(6)

        col.addWidget(QLabel(strings.SETTINGS_RECORDER, objectName="fieldLabel"))
        row = QHBoxLayout()
        self.recorder = QLineEdit(settings.recorder_path())
        self.recorder.setPlaceholderText(r"C:\Program Files\Audacity\Audacity.exe")
        row.addWidget(self.recorder, 1)
        browse = QPushButton(strings.SETTINGS_BROWSE)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        col.addLayout(row)
        hint = QLabel(strings.SETTINGS_RECORDER_HINT, objectName="muted")
        hint.setWordWrap(True)
        col.addWidget(hint)
        col.addSpacing(10)

        col.addWidget(QLabel(strings.SETTINGS_HOTKEY, objectName="fieldLabel"))
        template = strings.SETTINGS_HOTKEY_OK if hotkey_ok else strings.SETTINGS_HOTKEY_FAIL
        status = QLabel(
            template.format(keys=hotkey_label), objectName="muted" if hotkey_ok else "warning"
        )
        status.setWordWrap(True)
        col.addWidget(status)
        col.addSpacing(8)

        buttons = QDialogButtonBox()
        save = buttons.addButton(strings.SAVE, QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("primary")
        save.setDefault(True)
        buttons.addButton(strings.CANCEL, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.recorder.setFocus()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            strings.SETTINGS_PROGRAM_DIALOG,
            self.recorder.text(),
            strings.SETTINGS_PROGRAM_FILTER,
        )
        if path:
            self.recorder.setText(path.replace("/", "\\"))

    def accept(self) -> None:
        self._settings.set_recorder_path(self.recorder.text())
        super().accept()
