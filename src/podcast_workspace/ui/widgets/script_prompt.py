"""The script prompt of an episode: its brief on one side, the prompt it makes on the other.

Opened from the episode workspace's header. The brief (what the episode is about, its
format, audience, depth, approach, mood, register and length) is the episode's own and
is saved as it is edited, so the prompt is the same the next time it is opened. The
draft is the episode's notes, written where they always are; here they are only ticked
in or out, so a to-do note or a script pasted back from the AI stays out of the prompt.

The prompt is rebuilt from the template on every change (`domain/script_prompt.py`): what
is copied is always what is on screen.
"""

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import Episode
from podcast_workspace.domain.script_brief import DEPTHS, MAX_MINUTES, ScriptBrief
from podcast_workspace.domain.script_prompt import WORDS_PER_MINUTE, ScriptMaterial, build_prompt
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits, show_error
from podcast_workspace.ui.widgets.flow_layout import FlowLayout

SAVE_DELAY_MS = 700
COPIED_MS = 2000
ABOUT_LINES = 5


def _chip(text: str) -> QToolButton:
    chip = QToolButton(objectName="toggleChip", text=text, checkable=True)
    chip.setCursor(Qt.CursorShape.PointingHandCursor)
    return chip


class _Chips(QWidget):
    """A row of chips, any number on (`exclusive=False`) or exactly one."""

    def __init__(self, labels: dict, exclusive: bool, on_change: Callable[[], None]) -> None:
        super().__init__()
        flow = FlowLayout(self)
        self.group = QButtonGroup(self, exclusive=exclusive)
        self.chips: dict[object, QToolButton] = {}
        for key, label in labels.items():
            chip = _chip(label)
            self.group.addButton(chip)
            flow.addWidget(chip)
            self.chips[key] = chip
        self.group.buttonToggled.connect(lambda _b, _on: on_change())

    def set_checked(self, keys: object) -> None:
        wanted = keys if isinstance(keys, frozenset) else {keys}
        for key, chip in self.chips.items():
            chip.blockSignals(True)
            chip.setChecked(key in wanted)
            chip.blockSignals(False)

    def checked(self) -> list[object]:
        return [key for key, chip in self.chips.items() if chip.isChecked()]

    def first(self) -> QAbstractButton:
        return next(iter(self.chips.values()))


class ScriptPromptDialog(QDialog):
    def __init__(
        self, parent: QWidget, workspace: Workspace, episode: Episode, material: ScriptMaterial
    ) -> None:
        super().__init__(parent)
        assert episode.id is not None
        self._ws = workspace
        self._episode_id = episode.id
        self._material = material
        self._brief = self._saved = self._initial = episode.brief
        self._loading = True
        self.setWindowTitle(strings.SP_WINDOW_TITLE.format(title=episode.title))
        self.resize(1120, 760)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)
        root.addWidget(self._build_form(), 1)
        root.addLayout(self._build_prompt(), 1)

        self._timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._timer.timeout.connect(self._save)
        self._copied = QTimer(self, singleShot=True, interval=COPIED_MS)
        self._copied.timeout.connect(lambda: self.copy_button.setText(strings.SP_COPY))
        self._fill()
        self._loading = False
        self._refresh()
        self.about.setFocus()

    # layout -------------------------------------------------------------------------------
    def _build_form(self) -> QScrollArea:
        form = QWidget()
        col = QVBoxLayout(form)
        col.setContentsMargins(0, 0, 12, 0)
        col.setSpacing(6)
        col.addWidget(QLabel(strings.SP_BRIEF, objectName="dialogTitle"))
        hint = QLabel(strings.SP_BRIEF_HINT, objectName="muted", wordWrap=True)
        col.addWidget(hint)

        self.about = QPlainTextEdit()
        self.about.setPlaceholderText(strings.SP_ABOUT_PLACEHOLDER)
        self.about.setTabChangesFocus(True)
        line = self.about.fontMetrics().lineSpacing()
        self.about.setFixedHeight(line * ABOUT_LINES + 18)
        self.about.textChanged.connect(self._changed)
        self._field(col, strings.SP_ABOUT, self.about)

        self.formats = _Chips(strings.SP_FORMATS, False, self._changed)
        self._field(col, strings.SP_FORMAT, self.formats)
        self.audiences = _Chips(strings.SP_AUDIENCES, False, self._changed)
        self._field(col, strings.SP_AUDIENCE, self.audiences)

        self.depth = _Chips(
            {
                d: strings.SP_DEPTH_CHIP.format(n=local_digits(d), name=strings.SP_DEPTHS[d])
                for d in DEPTHS
            },
            True,
            self._changed,
        )
        self.depth_hint = QLabel(objectName="muted", wordWrap=True)
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(self.depth)
        box.addWidget(self.depth_hint)
        holder = QWidget()
        holder.setLayout(box)
        box.setContentsMargins(0, 0, 0, 0)
        self._field(col, strings.SP_DEPTH, holder)

        self.approaches = _Chips(strings.SP_APPROACHES, False, self._changed)
        self._field(col, strings.SP_APPROACH, self.approaches)
        self.moods = _Chips(strings.SP_MOODS, False, self._changed)
        self._field(col, strings.SP_MOOD, self.moods)
        self.register = _Chips(strings.SP_REGISTERS, True, self._changed)
        self._field(col, strings.SP_REGISTER, self.register)

        length = QHBoxLayout()
        length.setSpacing(10)
        self.minutes = QSpinBox()
        self.minutes.setRange(0, MAX_MINUTES)
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(strings.SP_MINUTES_SUFFIX)
        self.minutes.setSpecialValueText(strings.SP_MINUTES_FREE)
        self.minutes.valueChanged.connect(self._changed)
        self.words = QLabel(objectName="muted")
        length.addWidget(self.minutes)
        length.addWidget(self.words)
        length.addStretch(1)
        holder = QWidget()
        holder.setLayout(length)
        length.setContentsMargins(0, 0, 0, 0)
        self._field(col, strings.SP_LENGTH, holder)

        col.addSpacing(6)
        col.addWidget(QLabel(strings.SP_MATERIAL, objectName="sectionTitle"))
        self.notes: dict[int, QCheckBox] = {}
        col.addWidget(QLabel(strings.SP_DRAFT, objectName="fieldLabel"))
        if not self._material.notes:
            col.addWidget(QLabel(strings.SP_DRAFT_EMPTY, objectName="muted", wordWrap=True))
        for note in self._material.notes:
            first = note.body.strip().splitlines()[0][:40] if note.body.strip() else ""
            check = QCheckBox(note.title or first or strings.UNTITLED_NOTE)
            check.toggled.connect(self._changed)
            col.addWidget(check)
            self.notes[note.note_id] = check
        if self._material.notes:
            col.addWidget(QLabel(strings.SP_DRAFT_HINT, objectName="muted", wordWrap=True))
        col.addSpacing(4)
        col.addWidget(QLabel(strings.SP_IDEAS, objectName="fieldLabel"))
        ideas = self._material.ideas
        text = (
            strings.SP_IDEAS_COUNT.format(n=local_digits(len(ideas)))
            if ideas
            else strings.SP_IDEAS_NONE
        )
        col.addWidget(QLabel(text, objectName="muted", wordWrap=True))
        if self._material.unread_voices:
            unread = QLabel(
                strings.SP_UNREAD.format(
                    names=strings.LIST_SEPARATOR.join(self._material.unread_voices)
                ),
                objectName="muted",
                wordWrap=True,
            )
            col.addWidget(unread)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(form)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(440)
        return scroll

    @staticmethod
    def _field(col: QVBoxLayout, title: str, widget: QWidget) -> None:
        col.addSpacing(8)
        col.addWidget(QLabel(title, objectName="fieldLabel"))
        col.addWidget(widget)

    def _build_prompt(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel(strings.SP_PROMPT, objectName="dialogTitle"))
        head.addStretch(1)
        self.size_label = QLabel(objectName="muted")
        head.addWidget(self.size_label)
        col.addLayout(head)
        col.addWidget(QLabel(strings.SP_PROMPT_HINT, objectName="muted", wordWrap=True))
        self.prompt = QPlainTextEdit(objectName="noteBody", readOnly=True)
        # The prompt is Persian in either UI language: right to left and right-aligned, or a
        # line opening with a markdown "#" or "-" is laid out with the mark at its far end.
        option = self.prompt.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        option.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        self.prompt.document().setDefaultTextOption(option)
        col.addWidget(self.prompt, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(strings.SP_CLOSE)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        self.copy_button = QPushButton(strings.SP_COPY, objectName="primary")
        self.copy_button.clicked.connect(self._copy)
        buttons.addWidget(self.copy_button)
        col.addLayout(buttons)
        return col

    # state --------------------------------------------------------------------------------
    def _fill(self) -> None:
        brief = self._brief
        self.about.setPlainText(brief.about)
        self.formats.set_checked(brief.formats)
        self.audiences.set_checked(brief.audiences)
        self.depth.set_checked(brief.depth)
        self.approaches.set_checked(brief.approaches)
        self.moods.set_checked(brief.moods)
        self.register.set_checked(brief.register)
        self.minutes.setValue(brief.minutes)
        for note_id, check in self.notes.items():
            check.setChecked(note_id not in brief.left_out_notes)

    def _read(self) -> ScriptBrief:
        depth = self.depth.checked()
        register = self.register.checked()
        # Notes no longer in the episode keep their mark: it costs nothing and is harmless.
        left_out = {n for n in self._brief.left_out_notes if n not in self.notes}
        left_out |= {n for n, check in self.notes.items() if not check.isChecked()}
        return replace(
            self._brief,
            about=self.about.toPlainText(),
            formats=frozenset(self.formats.checked()),
            audiences=frozenset(self.audiences.checked()),
            depth=depth[0] if depth else self._brief.depth,
            approaches=frozenset(self.approaches.checked()),
            moods=frozenset(self.moods.checked()),
            register=register[0] if register else self._brief.register,
            minutes=self.minutes.value(),
            left_out_notes=frozenset(left_out),
        )

    def _changed(self) -> None:
        if self._loading:
            return
        self._brief = self._read()
        self._refresh()
        self._timer.start()

    def _refresh(self) -> None:
        brief = self._brief
        self.depth_hint.setText(strings.SP_DEPTH_HINTS[brief.depth])
        self.words.setText(
            strings.SP_WORDS.format(n=local_digits(brief.minutes * WORDS_PER_MINUTE))
            if brief.minutes
            else ""
        )
        text = build_prompt(self._material, brief)
        bar = self.prompt.verticalScrollBar()
        keep = bar.value()  # a tick must not throw the reader back to the top
        self.prompt.setPlainText(text)
        bar.setValue(keep)
        self.size_label.setText(strings.SP_PROMPT_SIZE.format(n=local_digits(len(text.split()))))

    def _save(self) -> None:
        self._timer.stop()
        if self._brief == self._saved:
            return
        try:
            self._ws.episodes.set_brief(self._episode_id, self._brief)
        except Exception as exc:
            show_error(self, exc)
            return
        self._saved = self._brief

    @property
    def changed(self) -> bool:
        """Whether the brief was saved with something new (the episode was touched)."""
        return self._saved != self._initial

    def _copy(self) -> None:
        self._save()
        QGuiApplication.clipboard().setText(self.prompt.toPlainText())
        self.copy_button.setText(strings.SP_COPIED)
        self._copied.start()

    def done(self, result: int) -> None:
        self._save()  # closed with Esc or the window's ✕ too
        super().done(result)
