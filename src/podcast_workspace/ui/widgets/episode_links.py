"""From an idea to an episode: the menu that puts ideas into episodes, and the row on an
idea's editor that says which episodes it is already in.

One menu, wherever it opens (the editor's button, a row's right-click, a selection of
several). «New episode from this idea» comes first — it is what cannot be done from
anywhere else — then the episodes being worked on, most recent first, each ticked when
the idea is already in it. Ticking puts the idea in, unticking takes it out, the way a
label menu works. Published episodes and anything past the first few are one more
click away («All episodes…»), so the menu stays short enough to read at a glance.

With several ideas, a tick means every one of them is in that episode; choosing an
unticked episode puts in the ones that are missing.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from podcast_workspace.domain.entities import Episode, EpisodeStatus
from podcast_workspace.domain.smart_links import LinkKind
from podcast_workspace.services.content_services import ItemRef
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits, show_error
from podcast_workspace.ui.widgets.flow_layout import FlowLayout
from podcast_workspace.ui.widgets.picker import PickerDialog

RECENT_EPISODES = 8
MENU_TITLE_WIDTH = 320  # px; longer episode titles are elided in the menu


def _holds(episode: Episode, item: ItemRef) -> bool:
    kind, item_id = item
    return item_id in (episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids)


def _last_worked_on(episode: Episode) -> float:
    opened = episode.last_opened_at or episode.updated_at
    return max(opened, episode.updated_at).timestamp()


class EpisodeMenu(QMenu):
    """Put the items `items()` returns into an episode, or start one from them."""

    created = Signal(int)  # episode id: a new episode, made from the items
    changed = Signal(int, bool)  # episode id, whether the items went in (or came out)

    def __init__(
        self, workspace: Workspace, parent: QWidget, items: Callable[[], list[ItemRef]]
    ) -> None:
        super().__init__(strings.ADD_TO_EPISODE, parent)
        self._ws = workspace
        self._items = items
        self.setToolTipsVisible(True)
        self.aboutToShow.connect(self._fill)

    def _fill(self) -> None:
        self.clear()
        items = self._items()
        if not items:
            return
        n = len(items)
        new_label = (
            strings.NEW_EPISODE_FROM_ONE
            if n == 1
            else strings.NEW_EPISODE_FROM_MANY.format(n=local_digits(n))
        )
        self.addAction(new_label, lambda: self._create(items))
        try:
            episodes = self._ws.episodes.list_all()
        except Exception:
            episodes = []
        if not episodes:
            return
        self.addSeparator()
        recent = sorted(
            (e for e in episodes if e.status is not EpisodeStatus.PUBLISHED),
            key=_last_worked_on,
            reverse=True,
        )[:RECENT_EPISODES]
        metrics = self.fontMetrics()
        for episode in recent:
            assert episode.id is not None
            title = metrics.elidedText(episode.title, Qt.TextElideMode.ElideRight, MENU_TITLE_WIDTH)
            action = self.addAction(
                strings.EPISODE_MENU_ITEM.format(
                    title=title, status=strings.STATUS_LABELS[episode.status]
                )
            )
            action.setToolTip(episode.title)
            action.setCheckable(True)
            action.setChecked(all(_holds(episode, item) for item in items))
            action.triggered.connect(
                lambda checked, eid=episode.id: self._set(eid, items, bool(checked))
            )
        if len(episodes) > len(recent):
            self.addSeparator()
            self.addAction(strings.EPISODE_MENU_ALL, lambda: self._pick(items, episodes))

    def _create(self, items: list[ItemRef]) -> None:
        try:
            episode = self._ws.episodes.create_from(items)
        except Exception as exc:
            show_error(self.parentWidget(), exc)
            return
        assert episode.id is not None
        self.created.emit(episode.id)

    def _set(self, episode_id: int, items: list[ItemRef], linked: bool) -> None:
        try:
            self._ws.episodes.set_linked(episode_id, items, linked)
        except Exception as exc:
            show_error(self.parentWidget(), exc)
            return
        self.changed.emit(episode_id, linked)

    def _pick(self, items: list[ItemRef], episodes: list[Episode]) -> None:
        """Every episode that does not hold all of them yet, published ones included."""
        seasons = {s.id: s.title for s in self._ws.seasons.list_all()}
        rows = []
        for episode in episodes:
            if episode.id is None or all(_holds(episode, item) for item in items):
                continue
            status = strings.STATUS_LABELS[episode.status]
            season = seasons.get(episode.season_id) if episode.season_id is not None else None
            rows.append((episode.id, episode.title, f"{season}  ·  {status}" if season else status))
        dialog = PickerDialog(self.parentWidget(), strings.EPISODE_PICK_TITLE, rows)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for episode_id in dialog.chosen():
            self._set(episode_id, items, True)


class EpisodeLinksRow(QWidget):
    """«Episodes: [one] [another]   Add to episode ▾» — under an idea's tags.

    Each episode is a link that opens it; the button holds the `EpisodeMenu`. A draft
    (an idea not saved yet) has nothing to put anywhere, so the button waits.
    """

    open_episode = Signal(int)
    created = Signal(int)
    changed = Signal(int, bool)

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self._ws = workspace
        self._item: ItemRef | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.label = QLabel(strings.IDEA_EPISODES_LABEL, objectName="fieldLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label)
        self._links = QWidget()
        self._flow = FlowLayout(self._links)
        row.addWidget(self._links, 1)
        self.add_button = QPushButton(strings.ADD_TO_EPISODE, objectName="flatButton")
        self.add_button.setToolTip(strings.ADD_TO_EPISODE_TOOLTIP)
        self.menu = EpisodeMenu(workspace, self.add_button, lambda: self.items)
        self.menu.created.connect(self.created)
        self.menu.changed.connect(self._on_changed)
        self.add_button.setMenu(self.menu)
        row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)

    @property
    def items(self) -> list[ItemRef]:
        return [] if self._item is None else [self._item]

    def set_item(self, kind: LinkKind | None, item_id: int | None = None) -> None:
        self._item = None if kind is None or item_id is None else (kind, item_id)
        self.add_button.setEnabled(self._item is not None)
        self.reload()

    def reload(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)  # gone now, not at the next turn of the event loop
                widget.deleteLater()
        episodes: list[Episode] = []
        if self._item is not None:
            try:
                episodes = self._ws.episodes.episodes_with(*self._item)
            except Exception:
                episodes = []
        for episode in episodes:
            assert episode.id is not None
            link = QPushButton(episode.title, objectName="linkButton")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(
                strings.IDEA_EPISODE_TOOLTIP.format(status=strings.STATUS_LABELS[episode.status])
            )
            link.clicked.connect(lambda _c=False, eid=episode.id: self.open_episode.emit(eid))
            self._flow.addWidget(link)
        if not episodes:
            self._flow.addWidget(QLabel(strings.IDEA_EPISODES_NONE, objectName="muted"))
        self._links.updateGeometry()

    def _on_changed(self, episode_id: int, linked: bool) -> None:
        self.reload()
        self.changed.emit(episode_id, linked)
