"""Asking what to do with audio whose name a voice already has, and what goes with it.

An import never overwrites on its own (`VoiceService.import_files`): before one starts,
the page asks here about every file that would clash — replace the existing voice's audio,
keep both (the new one numbered), or leave it out.

Replacing or keeping both then asks which details go with the file (`ask_details`, shared
with «خروجی گرفتن»): tags, notes, transcript, episode links, each with how many there are.
For a replacement all are ticked (unticked ones are deleted from the voice); for a new copy
none are (ticked ones are copied from the original). A detail the voice has none of is
greyed out, and when it has none at all nothing is asked.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.voice_store import Detail, NameAnswer, NameChoice
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits

DIALOG_WIDTH = 380


def _detail_labels() -> list[tuple[Detail, str]]:
    return [
        (Detail.TAGS, strings.DETAIL_TAGS),
        (Detail.NOTES, strings.DETAIL_NOTES),
        (Detail.TRANSCRIPT, strings.DETAIL_TRANSCRIPT),
        (Detail.EPISODES, strings.DETAIL_EPISODES),
    ]


class _DetailsDialog(QDialog):
    def __init__(self, parent: QWidget, replace: bool, counts: dict[Detail, int]) -> None:
        super().__init__(parent)
        title = strings.DETAILS_REPLACE_TITLE if replace else strings.DETAILS_NEW_TITLE
        self.setWindowTitle(title)
        self.setMinimumWidth(DIALOG_WIDTH)
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(10)
        col.addWidget(QLabel(title, objectName="dialogTitle"))
        body = QLabel(strings.DETAILS_REPLACE_BODY if replace else strings.DETAILS_NEW_BODY)
        body.setWordWrap(True)
        col.addWidget(body)
        if replace:
            warning = QLabel(strings.DETAILS_REPLACE_WARNING, objectName="muted")
            warning.setWordWrap(True)
            col.addWidget(warning)
        self._boxes: list[tuple[Detail, QCheckBox]] = []
        for detail, label in _detail_labels():
            n = counts.get(detail, 0)
            if not n:
                label = strings.DETAIL_NONE.format(label=label)
            elif detail is not Detail.TRANSCRIPT:
                label = strings.DETAIL_COUNT.format(label=label, n=local_digits(n))
            box = QCheckBox(label)
            box.setEnabled(bool(n))
            box.setChecked(replace and bool(n))
            col.addWidget(box)
            self._boxes.append((detail, box))
        buttons = QDialogButtonBox()
        ok = buttons.addButton(
            strings.DETAILS_REPLACE_OK if replace else strings.DETAILS_NEW_OK,
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        ok.setObjectName("primary")
        ok.setDefault(True)
        buttons.addButton(strings.CANCEL, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addSpacing(6)
        col.addWidget(buttons)

    def chosen(self) -> Detail:
        result = Detail.NONE
        for detail, box in self._boxes:
            if box.isChecked():
                result |= detail
        return result


def ask_details(
    parent: QWidget, workspace: Workspace, voice_id: int, replace: bool
) -> Detail | None:
    """Which details of voice `voice_id` go with the file: kept by a replacement, copied
    to a new copy. None: cancelled."""
    counts = workspace.voices.detail_counts(voice_id)
    if not any(counts.values()):
        return Detail.ALL if replace else Detail.NONE  # nothing to keep or copy
    dialog = _DetailsDialog(parent, replace, counts)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen()


def ask_name_choices(
    parent: QWidget, workspace: Workspace, conflicts: dict[Path, Voice]
) -> dict[Path, NameAnswer]:
    """One answer per clashing file. Esc (or closing the box) leaves that file out;
    cancelling the details box goes back to the first question."""
    answers: dict[Path, NameAnswer] = {}
    pending = list(conflicts)
    while pending:
        path = pending.pop(0)
        box = QMessageBox(QMessageBox.Icon.Question, strings.NAME_CONFLICT_TITLE, "", parent=parent)
        box.setText(strings.NAME_CONFLICT_BODY.format(name=strings.QUOTE.format(text=path.name)))
        box.setInformativeText(strings.NAME_CONFLICT_HINT)
        keep = box.addButton(strings.NAME_CONFLICT_KEEP_BOTH, QMessageBox.ButtonRole.AcceptRole)
        keep.setObjectName("primary")
        replace = box.addButton(strings.NAME_CONFLICT_REPLACE, QMessageBox.ButtonRole.YesRole)
        skip = box.addButton(strings.NAME_CONFLICT_SKIP, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)  # the answer that loses nothing
        box.setEscapeButton(skip)
        rest: QCheckBox | None = None
        if pending:
            rest = QCheckBox(strings.NAME_CONFLICT_ALL.format(n=local_digits(len(pending))))
            box.setCheckBox(rest)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (replace, keep):
            voice_id = conflicts[path].id
            assert voice_id is not None
            details = ask_details(parent, workspace, voice_id, clicked is replace)
            if details is None:
                pending.insert(0, path)
                continue
            choice = NameChoice.REPLACE if clicked is replace else NameChoice.KEEP_BOTH
            answer = NameAnswer(choice, details)
        else:
            answer = NameAnswer(NameChoice.SKIP)
        answers[path] = answer
        if rest is not None and rest.isChecked():
            answers.update(dict.fromkeys(pending, answer))
            break
    return answers
