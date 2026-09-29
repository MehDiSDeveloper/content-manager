"""A season's brief: what the season is about and how it is laid out.

Two pieces, both on the Episodes page. The card sits in the list column over the
episodes of the season on show, so the first lines of what the season is for are in
sight whenever its episodes are; clicking it opens the brief in the detail pane, where
an episode's workspace would otherwise be.
"""

from collections import Counter

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QHideEvent, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.entities import EpisodeStatus, Season
from podcast_workspace.services.workspace import Workspace
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import AppEvents, local_digits, show_error

AUTOSAVE_DELAY_MS = 700
CARD_LINES = 2
CARD_MARGINS = (14, 10, 14, 10)


def clamp_lines(text: str, font: QFont, width: int, lines: int) -> list[str]:
    """Wrap `text` to `width` and keep the first `lines` lines, the last one elided."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    spans: list[tuple[int, int]] = []
    layout.beginLayout()
    while len(spans) < lines:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    layout.endLayout()
    if not spans:
        return []
    kept = [text[start : start + length].strip() for start, length in spans[:-1]]
    rest = text[spans[-1][0] :].strip()
    kept.append(QFontMetrics(font).elidedText(rest, Qt.TextElideMode.ElideRight, width))
    return kept


class SeasonCard(QPushButton):
    """The season on show, in two lines of its brief. Checked while the brief is open."""

    def __init__(self) -> None:
        super().__init__(objectName="seasonCard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(strings.SEASON_BRIEF_TOOLTIP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(*CARD_MARGINS)
        box.setSpacing(3)
        self.caption = QLabel(strings.SEASON_BRIEF_CAPTION, objectName="fieldLabel")
        self.body = QLabel(objectName="seasonCardText")
        for label in (self.caption, self.body):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(label)
        self._summary = ""

    def set_summary(self, summary: str) -> None:
        self._summary = " ".join(summary.split())  # its lines, run together
        self._fit()

    def _fit(self) -> None:
        empty = not self._summary
        text = strings.SEASON_BRIEF_CARD_EMPTY if empty else self._summary
        width = max(40, self.width() - CARD_MARGINS[0] - CARD_MARGINS[2])
        lines = clamp_lines(text, self.body.font(), width, CARD_LINES)
        self.body.setText("\n".join(lines))
        self.body.setProperty("empty", empty)
        self.body.style().unpolish(self.body)
        self.body.style().polish(self.body)
        line = QFontMetrics(self.body.font()).lineSpacing()
        self.setFixedHeight(
            CARD_MARGINS[1]
            + CARD_MARGINS[3]
            + self.caption.sizeHint().height()
            + 3
            + line * max(1, len(lines))
            + 2  # the focus frame
        )

    def resizeEvent(self, event: object) -> None:  # type: ignore[override]
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._fit()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fit()


class SeasonBriefPage(QWidget):
    """The season's name, where its episodes stand, and its brief in two columns: what
    it is about beside how it is laid out. Everything saves as it is typed."""

    saved = Signal(object)  # Season, after its title or brief changed
    list_toggle_requested = Signal()

    def __init__(self, workspace: Workspace, events: AppEvents) -> None:
        super().__init__()
        self._ws = workspace
        self._events = events
        self._season: Season | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.list_toggle = QToolButton(objectName="chromeButton")
        self.list_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_toggle.clicked.connect(self.list_toggle_requested.emit)
        header.addWidget(self.list_toggle)
        self.title_edit = QLineEdit(objectName="titleEdit")
        self.title_edit.setPlaceholderText(strings.SEASON_TITLE_PLACEHOLDER)
        self.title_edit.editingFinished.connect(self._save_title)
        header.addWidget(self.title_edit, 1)
        root.addLayout(header)
        self.progress = QLabel(objectName="muted")
        root.addWidget(self.progress)

        # Side by side rather than stacked: each column keeps a readable line length on
        # a wide pane, and the goal stays in view while the structure is written.
        body = QHBoxLayout()
        body.setSpacing(18)
        self.summary = self._column(
            body, strings.SEASON_SUMMARY, strings.SEASON_SUMMARY_PLACEHOLDER
        )
        self.outline = self._column(
            body, strings.SEASON_OUTLINE, strings.SEASON_OUTLINE_PLACEHOLDER
        )
        root.addLayout(body, 1)

        self._timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self._save_brief)

    def _column(self, row: QHBoxLayout, title: str, placeholder: str) -> QPlainTextEdit:
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(QLabel(title, objectName="sectionTitle"))
        edit = QPlainTextEdit(objectName="noteBody")
        edit.setPlaceholderText(placeholder)
        edit.setTabChangesFocus(True)
        edit.textChanged.connect(self._schedule_save)
        col.addWidget(edit, 1)
        row.addLayout(col, 1)
        return edit

    # public -------------------------------------------------------------------------------
    @property
    def season_id(self) -> int | None:
        return None if self._season is None else self._season.id

    def open(self, season_id: int) -> bool:
        """Show a season, or read the one on show again. What is being typed is saved
        first and read back, so the caret and the scroll stay where they are."""
        self.flush()
        try:
            season = self._ws.seasons.get(season_id)
            episodes = [e for e in self._ws.episodes.list_all() if e.season_id == season_id]
        except Exception:
            return False
        same = self._season is not None and self._season.id == season.id
        self._season = season
        self._loading = True
        if not (same and self.title_edit.text() == season.title):
            self.title_edit.setText(season.title)
            self.title_edit.setCursorPosition(0)
        for edit, text in ((self.summary, season.summary), (self.outline, season.outline)):
            if not (same and edit.toPlainText() == text):
                edit.setPlainText(text)
        self._loading = False
        self._show_progress([e.status for e in episodes])
        return True

    def clear(self) -> None:
        self.flush()
        self._season = None

    def flush(self) -> None:
        if self.title_edit.isModified():
            self._save_title()
        if self._timer.isActive():
            self._timer.stop()
            self._save_brief()

    def focus_main(self) -> None:
        self.summary.setFocus()

    # saving -------------------------------------------------------------------------------
    def _show_progress(self, statuses: list[EpisodeStatus]) -> None:
        """How many episodes, and how far along: each stage that has any, in order."""
        if not statuses:
            self.progress.setText(strings.SEASON_PROGRESS_EMPTY)
            return
        counts = Counter(statuses)
        stages = "  ·  ".join(
            strings.SEASON_PROGRESS_STAGE.format(
                stage=strings.STATUS_LABELS[status], n=local_digits(counts[status])
            )
            for status in EpisodeStatus
            if counts[status]
        )
        self.progress.setText(
            strings.SEASON_PROGRESS.format(n=local_digits(len(statuses)), stages=stages)
        )

    def _schedule_save(self) -> None:
        if not self._loading and self._season is not None:
            self._timer.start()

    def _save_title(self) -> None:
        self.title_edit.setModified(False)
        season = self._season
        if season is None or season.id is None:
            return
        title = self.title_edit.text().strip()
        if not title or title == season.title:
            self.title_edit.setText(season.title)  # a season always has a name
            return
        try:
            saved = self._ws.seasons.rename(season.id, title)
        except Exception as exc:
            show_error(self, exc)
            self.title_edit.setText(season.title)
            return
        self._saved(saved)

    def _save_brief(self) -> None:
        season = self._season
        if season is None or season.id is None:
            return
        try:
            saved = self._ws.seasons.write_brief(
                season.id, self.summary.toPlainText(), self.outline.toPlainText()
            )
        except Exception as exc:
            show_error(self, exc)
            return
        if (saved.summary, saved.outline) != (season.summary, season.outline):
            self._saved(saved)

    def _saved(self, season: Season) -> None:
        self._season = season
        self.saved.emit(season)
        self._events.data_changed.emit()

    def hideEvent(self, event: QHideEvent) -> None:
        self.flush()
        super().hideEvent(event)
