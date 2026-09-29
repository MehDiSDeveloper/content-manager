"""«خروجی گرفتن»: an audio idea written out with the player's pause
trimming and volume (`services/voice_render.py`).

It asks first — a new audio beside this one («name 01», with its tags, notes and
transcript) or this one's sound replaced — then makes the file in the background behind a
progress box that can cancel it. Replacing lets go of the file in the player first, since
Windows will not write over a file that is open.
"""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from podcast_workspace.audio.render import RenderCancelledError
from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.voice_render import PlaybackEdit
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.player.player_widget import PlayerWidget
from podcast_workspace.ui.player.silence_control import seconds_label
from podcast_workspace.ui.support import format_clock, local_digits, run_async, show_error

PROGRESS_STEPS = 1000


def _ask(
    parent: QWidget, voice: Voice, copy_name: str, edit: PlaybackEdit, level: int, keep_ms: int
) -> bool | None:
    """True to replace, False for a new audio, None to leave it."""
    quote = strings.QUOTE.format
    lines = [strings.VOICE_SAVE_BODY.format(name=quote(text=Path(voice.file_path).name))]
    if edit.cuts:
        percent = round(100 * edit.saved_ms / voice.duration_ms) if voice.duration_ms else 0
        lines.append(
            "• "
            + strings.VOICE_SAVE_TRIM.format(
                saved=format_clock(edit.saved_ms),
                percent=local_digits(percent),
                keep=seconds_label(keep_ms),
            )
        )
    else:
        lines.append("• " + strings.VOICE_SAVE_NO_TRIM)
    lines.append(
        "• "
        + (
            strings.VOICE_SAVE_LEVEL.format(percent=local_digits(level))
            if edit.gain < 0.999
            else strings.VOICE_SAVE_FULL_LEVEL
        )
    )
    box = QMessageBox(QMessageBox.Icon.Question, strings.VOICE_SAVE_TITLE, "", parent=parent)
    box.setText("\n".join(lines))
    box.setInformativeText(strings.VOICE_SAVE_HINT.format(copy=quote(text=copy_name)))
    new = box.addButton(strings.VOICE_SAVE_NEW, QMessageBox.ButtonRole.AcceptRole)
    new.setObjectName("primary")
    replace = box.addButton(strings.VOICE_SAVE_REPLACE, QMessageBox.ButtonRole.YesRole)
    cancel = box.addButton(strings.CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(new)  # the answer that loses nothing
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is new:
        return False
    if clicked is replace:
        return True
    return None


class SaveAsHeard(QObject):
    """The flow for one player pane. `finished` carries the voice to show afterwards (the
    new one, the replaced one, or — after a failure or cancel — the original), whether
    anything was saved, and whether it was a replacement."""

    finished = Signal(object, bool, bool)  # Voice, saved, replaced
    _progress = Signal(int)

    def __init__(self, parent: QWidget, workspace: Workspace, player: PlayerWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._ws = workspace
        self._player = player
        self.running = False

    def start(self, voice: Voice) -> None:
        if self.running or voice.id is None or not self._player.is_current():
            return
        player = self._player.player
        if player.skip_silence and not player.pauses_known:
            QMessageBox.information(self._parent, strings.VOICE_SAVE_TITLE, strings.VOICE_SAVE_WAIT)
            return
        edit = PlaybackEdit(player.active_cuts(), player.level_gain)
        if edit.changes_nothing:
            QMessageBox.information(
                self._parent, strings.VOICE_SAVE_TITLE, strings.VOICE_SAVE_NOTHING
            )
            return
        try:
            copy_name = self._ws.voice_render.copy_name(voice.id)
        except Exception as exc:
            show_error(self._parent, exc)
            return
        replace = _ask(self._parent, voice, copy_name, edit, player.level, player.keep_pause_ms)
        if replace is None:
            return
        if replace:
            self._player.close_voice()  # Windows cannot write over a file being played
        self._run(voice, edit, replace)

    def _run(self, voice: Voice, edit: PlaybackEdit, replace: bool) -> None:
        assert voice.id is not None
        voice_id = voice.id
        self.running = True
        dialog = QProgressDialog(
            strings.VOICE_SAVE_PROGRESS, strings.CANCEL, 0, PROGRESS_STEPS, self._parent
        )
        dialog.setWindowTitle(strings.VOICE_SAVE_TITLE)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(300)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        cancel = threading.Event()
        dialog.canceled.connect(cancel.set)
        self._progress.connect(dialog.setValue)

        def done(saved: Voice) -> None:
            self._end(dialog)
            self.finished.emit(saved, True, replace)

        def failed(exc: BaseException) -> None:
            self._end(dialog)
            if not isinstance(exc, RenderCancelledError):
                show_error(self._parent, exc)
            self.finished.emit(voice, False, replace)

        run_async(
            lambda: self._ws.voice_render.save(
                voice_id,
                edit,
                replace,
                cancel,
                lambda share: self._progress.emit(round(share * PROGRESS_STEPS)),
            ),
            done,
            failed,
        )

    def _end(self, dialog: QProgressDialog) -> None:
        self.running = False
        self._progress.disconnect(dialog.setValue)
        dialog.close()
        dialog.deleteLater()
