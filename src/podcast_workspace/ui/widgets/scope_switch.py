"""The three-way archive switch: active / all / archived (`domain/lifecycle.py`).

Pill tabs rather than a combo box: three short choices read at a glance, and the one in
force is always visible — which matters, because a list that silently leaves things out
is a list that looks like it lost them.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabBar

from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.ui import strings

_ORDER = (ArchiveScope.ACTIVE, ArchiveScope.ALL, ArchiveScope.ARCHIVED)


class ScopeSwitch(QTabBar):
    scope_changed = Signal(object)  # ArchiveScope

    def __init__(self, tooltip: str = "") -> None:
        super().__init__(objectName="noteTabs")
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        for scope in _ORDER:
            self.addTab(strings.ARCHIVE_SCOPES[scope.value])
        self.setToolTip(tooltip or strings.ARCHIVE_SCOPE_TOOLTIP)
        self.currentChanged.connect(lambda index: self.scope_changed.emit(_ORDER[index]))

    def scope(self) -> ArchiveScope:
        return _ORDER[max(0, self.currentIndex())]

    def set_scope(self, scope: ArchiveScope) -> None:
        """Without a signal: the caller reloads once, afterwards."""
        self.blockSignals(True)
        self.setCurrentIndex(_ORDER.index(scope))
        self.blockSignals(False)
