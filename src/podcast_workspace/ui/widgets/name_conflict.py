"""Asking what to do with audio whose name a voice already has.

An import never overwrites on its own (`VoiceService.import_files`): before one starts,
the page asks here about every file that would clash — replace the existing voice's audio,
keep both (the new one numbered), or leave it out.
"""

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from podcast_workspace.domain.entities import Voice
from podcast_workspace.services.voice_store import NameChoice
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits


def ask_name_choices(parent: QWidget, conflicts: dict[Path, Voice]) -> dict[Path, NameChoice]:
    """One answer per clashing file. Esc (or closing the box) leaves that file out."""
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
            choice = NameChoice.KEEP_BOTH
        else:
            choice = NameChoice.SKIP
        choices[path] = choice
        if rest is not None and rest.isChecked():
            choices.update(dict.fromkeys(pending, choice))
            break
    return choices
