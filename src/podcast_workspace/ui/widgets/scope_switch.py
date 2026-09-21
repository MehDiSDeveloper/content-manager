"""Pill switches: a few short, exclusive choices with the one in force always visible.

`ScopeSwitch` is the three-way archive switch: active / all / archived
(`domain/lifecycle.py`). Pill tabs rather than a combo box: three short choices read at a
glance, and the one in force is always visible — which matters, because a list that
silently leaves things out is a list that looks like it lost them.
"""

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabBar

from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.ui import strings


class ChoiceSwitch(QTabBar):
    """One pill per value; `labels` maps each value to what the pill says."""

    choice_changed = Signal(object)

    def __init__(self, values: Sequence[object], labels: dict[object, str], tooltip: str) -> None:
        super().__init__(objectName="noteTabs")
        self._values = tuple(values)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setUsesScrollButtons(False)
        for value in self._values:
            self.addTab(labels[value])
        self.setToolTip(tooltip)
        self.currentChanged.connect(self._emit)

    def _emit(self, index: int) -> None:
        if index >= 0:
            self.choice_changed.emit(self._values[index])

    def choice(self) -> object:
        return self._values[max(0, self.currentIndex())]

    def set_choice(self, value: object) -> None:
        """Without a signal: the caller reloads once, afterwards."""
        self.blockSignals(True)
        self.setCurrentIndex(self._values.index(value))
        self.blockSignals(False)

    def set_label(self, value: object, text: str) -> None:
        self.setTabText(self._values.index(value), text)


_ORDER = (ArchiveScope.ACTIVE, ArchiveScope.ALL, ArchiveScope.ARCHIVED)


class ScopeSwitch(ChoiceSwitch):
    scope_changed = Signal(object)  # ArchiveScope

    def __init__(self, tooltip: str = "") -> None:
        labels: dict[object, str] = {s: strings.ARCHIVE_SCOPES[s.value] for s in _ORDER}
        super().__init__(_ORDER, labels, tooltip or strings.ARCHIVE_SCOPE_TOOLTIP)
        self.choice_changed.connect(self.scope_changed)

    def scope(self) -> ArchiveScope:
        choice = self.choice()
        assert isinstance(choice, ArchiveScope)
        return choice

    def set_scope(self, scope: ArchiveScope) -> None:
        self.set_choice(scope)
