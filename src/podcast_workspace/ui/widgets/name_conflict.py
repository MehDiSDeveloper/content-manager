"""Asking what to do with audio whose name a voice already has.

An import never overwrites on its own (`VoiceService.import_files`): before one starts,
the page asks here about every file that would clash — replace the existing voice's audio
(everything on it stays), keep both (the new one numbered), or leave it out. Keeping both
asks a second question (`ask_copy_details`, shared with «خروجی گرفتن»): should the new one
carry the existing one's tags, notes and transcript.
"""

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.voice_store import NameChoice
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits


def ask_copy_details(parent: QWidget) -> bool | None:
    """Whether a new copy carries the original's tags, notes and transcript (the box
    before this one named it). None: Esc."""
    box = QMessageBox(QMessageBox.Icon.Question, strings.COPY_DETAILS_TITLE, "", parent=parent)
    box.setText(strings.COPY_DETAILS_BODY)
    box.setInformativeText(strings.COPY_DETAILS_HINT)
    yes = box.addButton(strings.COPY_DETAILS_YES, QMessageBox.ButtonRole.YesRole)
    yes.setObjectName("primary")
    no = box.addButton(strings.COPY_DETAILS_NO, QMessageBox.ButtonRole.NoRole)
    cancel = box.addButton(strings.CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes)  # the answer that loses nothing
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is yes:
        return True
    if clicked is no:
        return False
    return None


def ask_name_choices(parent: QWidget, conflicts: dict[Path, Voice]) -> dict[Path, NameChoice]:
    """One answer per clashing file. Esc (or closing the box) leaves that file out; Esc
    on the second question goes back to the first."""
    choices: dict[Path, NameChoice] = {}
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
        if clicked is replace:
            choice = NameChoice.REPLACE
        elif clicked is keep:
            details = ask_copy_details(parent)
            if details is None:
                pending.insert(0, path)
                continue
            choice = NameChoice.KEEP_BOTH_WITH_DETAILS if details else NameChoice.KEEP_BOTH
        else:
            choice = NameChoice.SKIP
        choices[path] = choice
        if rest is not None and rest.isChecked():
            choices.update(dict.fromkeys(pending, choice))
            break
    return choices
