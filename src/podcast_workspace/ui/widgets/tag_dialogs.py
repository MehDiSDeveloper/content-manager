"""Dialogs of the tag manager: pick one tag (merge target) and create a new tag."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.services.tag_service import TagService
from podcast_workspace.ui import strings
from podcast_workspace.ui.widgets.tag_widgets import SuggestionList


class _ArrowKeysToList(QObject):
    def __init__(self, target: SuggestionList, parent: QObject) -> None:
        super().__init__(parent)
        self._target = target

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_Down:
                self._target.move(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._target.move(-1)
                return True
        return False


class TagPickerDialog(QDialog):
    """Choose one existing tag with the same forgiving matching as TagInput."""

    def __init__(
        self, tags: TagService, title: str, exclude_ids: set[int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self._tags = tags
        self._exclude = exclude_ids
        self.chosen_id: int | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(10)
        col.addWidget(QLabel(title, objectName="dialogTitle"))
        self._edit = QLineEdit(placeholderText=strings.TAG_FILTER_PLACEHOLDER)
        self._list = SuggestionList()
        self._edit.installEventFilter(_ArrowKeysToList(self._list, self))
        self._edit.textEdited.connect(self._refresh)
        self._edit.returnPressed.connect(self._list.activate_current)
        self._list.activated_value.connect(self._choose)
        col.addWidget(self._edit)
        col.addWidget(self._list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.CANCEL)
        pick = QPushButton(strings.TAG_PICK, objectName="primary")
        pick.clicked.connect(self._list.activate_current)
        buttons.addButton(pick, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._refresh("")

    def _refresh(self, text: str) -> None:
        if text.strip():
            found = [m.tag for m in self._tags.suggest(text, self._exclude, limit=12)]
        else:
            found = [t for t in self._tags.list_all() if t.id not in self._exclude]
        self._list.fill(found, max_visible=10)
        self._list.setVisible(True)

    def _choose(self, _kind: str, value: object) -> None:
        self.chosen_id = int(str(value))
        self.accept()


class NewTagDialog(QDialog):
    """Name a new tag while seeing similar existing ones; exact duplicates are blocked."""

    def __init__(self, tags: TagService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.TAG_NEW_TITLE)
        self.setMinimumWidth(420)
        self._tags = tags
        self.allow_similar = False

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(10)
        col.addWidget(QLabel(strings.TAG_NEW_TITLE, objectName="dialogTitle"))
        self.name_edit = QLineEdit(placeholderText=strings.TAG_NAME_PLACEHOLDER)
        self.name_edit.textEdited.connect(self._refresh)
        col.addWidget(self.name_edit)
        self._hint = QLabel(objectName="muted")
        self._hint.setWordWrap(True)
        col.addWidget(self._hint)
        self._similar = SuggestionList()
        self._similar.setEnabled(False)
        col.addWidget(self._similar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.CANCEL)
        self._create = QPushButton(strings.TAG_CREATE, objectName="primary")
        self._create.clicked.connect(self._accept)
        buttons.addButton(self._create, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.name_edit.returnPressed.connect(self._accept)
        self._refresh("")

    def _refresh(self, text: str) -> None:
        name = text.strip()
        exact = self._tags.find_exact(name) if name else None
        similar = self._tags.similar_to(name) if name else []
        similar += [
            m.tag for m in self._tags.suggest(name, limit=5) if name and m.tag not in similar
        ][: max(0, 5 - len(similar))]
        self._similar.fill(similar, max_visible=5)
        self._similar.setCurrentRow(-1)
        self.allow_similar = bool(similar) and exact is None
        if exact is not None:
            self._hint.setText(strings.TAG_EXACT_EXISTS.format(name=exact.name))
        else:
            self._hint.setText(strings.TAG_SIMILAR_HINT if similar else "")
        self._hint.setVisible(bool(self._hint.text()))
        self._create.setEnabled(bool(name) and exact is None)
        self._create.setText(strings.TAG_CREATE_ANYWAY if similar else strings.TAG_CREATE)

    def _accept(self) -> None:
        if self._create.isEnabled():
            self.accept()
