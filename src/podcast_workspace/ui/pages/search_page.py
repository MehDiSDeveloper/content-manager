"""Global search results. Fed by the search bar in the main window.

Two switches in the header decide what is searched: «in content» opens up note, idea and
transcript text (off, only titles, names and tags are read), and the archive switch
decides whether archived ideas are searched too. The kind tabs over the results say how
many of each kind were found and show one kind at a time. All three are back to their
defaults every time a search starts; while titles alone are searched, a line under the
tabs says how much more the content holds, one click away.
"""

import html

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.domain.search import SearchHit, SearchKind, SearchResult
from podcast_workspace.domain.text import find_spans, query_terms
from podcast_workspace.ui import strings
from podcast_workspace.ui.support import local_digits
from podcast_workspace.ui.widgets.scope_switch import ChoiceSwitch, ScopeSwitch

HIT_ROLE = Qt.ItemDataRole.UserRole
RESULTS_MAX_WIDTH = 880

ALL = "all"
# Which tab a hit belongs to. A note or a transcript goes with what it belongs to; a tag
# hit is in «all» only.
KIND_GROUPS: dict[SearchKind, str] = {
    SearchKind.EPISODE: "episode",
    SearchKind.EPISODE_NOTE: "episode",
    SearchKind.VOICE: "audio",
    SearchKind.TRANSCRIPT: "audio",
    SearchKind.TIMESTAMP_NOTE: "audio",
    SearchKind.IDEA_NOTE: "text",
}
GROUPS = (ALL, "episode", "audio", "text")


def highlight(text: str, terms: list[str]) -> str:
    """HTML-escape `text` and bold every occurrence of the (normalized) terms."""
    out: list[str] = []
    cursor = 0
    for start, end in find_spans(text, terms):
        out.append(html.escape(text[cursor:start]))
        out.append(f"<b>{html.escape(text[start:end])}</b>")
        cursor = end
    out.append(html.escape(text[cursor:]))
    return "".join(out)


def _display_title(hit: SearchHit) -> str:
    return hit.title if hit.title.strip() else strings.UNTITLED_NOTE


class HitWidget(QWidget):
    MARGIN_V = 8
    SPACING = 2

    def __init__(self, hit: SearchHit, terms: list[str]) -> None:
        super().__init__()
        self.lines = 1
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, self.MARGIN_V, 14, self.MARGIN_V)
        col.setSpacing(self.SPACING)
        top = QHBoxLayout()
        top.setSpacing(10)
        badge = QLabel(strings.KIND_LABELS[hit.kind], objectName="kindBadge")
        top.addWidget(badge)
        title = QLabel(highlight(_display_title(hit), terms), objectName="hitTitle")
        title.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(title, 1)
        col.addLayout(top)
        detail = hit.snippet
        if hit.via_tag:
            detail = strings.SEARCH_VIA_TAG.format(tag=hit.via_tag) + (
                f"  ·  {detail}" if detail else ""
            )
        shown_title = _display_title(hit).rstrip("…")
        if detail and not detail.lstrip("…").startswith(shown_title):
            snippet = QLabel(highlight(detail, terms), objectName="hitSnippet")
            snippet.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(snippet)
            self.lines = 2

    def row_height(self, base: QFont) -> int:
        """Item widgets report their size before layout; compute it from the fonts instead."""
        title_font = QFont(base)
        title_font.setPointSizeF(11)
        title = QFontMetrics(title_font).height() + 4  # badge padding
        body = QFontMetrics(base).height()
        extra = (body + self.SPACING) if self.lines == 2 else 0
        return title + extra + 2 * self.MARGIN_V + 12  # item padding + selection border


class SearchPage(QWidget):
    open_hit = Signal(object)  # SearchHit
    scope_changed = Signal()  # the archive or the content switch: search again

    def __init__(self) -> None:
        super().__init__()
        self.nav_title = strings.SEARCH_TITLE
        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 22, 32, 22)
        # Results are lines of text: past a readable measure the eye loses the row it
        # is on, so the column stops growing and the rest of the width stays empty.
        column = QWidget()
        column.setMaximumWidth(RESULTS_MAX_WIDTH)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        root = QVBoxLayout(column)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(QLabel(strings.SEARCH_TITLE, objectName="pageTitle"))
        header.addStretch(1)
        self.content = QToolButton(objectName="toggleChip", text=strings.CONTENT_SWITCH)
        self.content.setCheckable(True)
        self.content.setCursor(Qt.CursorShape.PointingHandCursor)
        self.content.setToolTip(strings.SEARCH_CONTENT_TOOLTIP)
        self.content.toggled.connect(lambda _on: self.scope_changed.emit())
        header.addWidget(self.content)
        self.scope_switch = ScopeSwitch(strings.SEARCH_SCOPE_TOOLTIP)
        self.scope_switch.scope_changed.connect(lambda _s: self.scope_changed.emit())
        header.addWidget(self.scope_switch)
        root.addLayout(header)
        tabs_row = QHBoxLayout()
        self.kinds = ChoiceSwitch(
            GROUPS, {g: strings.SEARCH_KINDS[g] for g in GROUPS}, strings.SEARCH_KIND_TOOLTIP
        )
        self.kinds.choice_changed.connect(lambda _k: self._render())
        tabs_row.addWidget(self.kinds)
        tabs_row.addStretch(1)
        root.addLayout(tabs_row)
        self.corrections = QLabel(objectName="muted")
        root.addWidget(self.corrections)
        self.more = QPushButton(objectName="linkButton")
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.setToolTip(strings.SEARCH_CONTENT_TOOLTIP)
        self.more.clicked.connect(lambda: self.content.setChecked(True))
        self.more.hide()
        root.addWidget(self.more, 0, Qt.AlignmentFlag.AlignLeading)
        self._result = SearchResult("", [], {})
        self.results = QListWidget(objectName="results")
        self.results.itemActivated.connect(self._activate)
        self.results.itemClicked.connect(self._activate)
        root.addWidget(self.results, 1)
        self.empty = QLabel(strings.SEARCH_EMPTY, objectName="emptyHint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)
        root.addStretch(0)

    def show_result(self, result: SearchResult) -> None:
        self._result = result
        counts = dict.fromkeys(GROUPS, 0)
        counts[ALL] = len(result.hits)
        for hit in result.hits:
            group = KIND_GROUPS.get(hit.kind)
            if group is not None:
                counts[group] += 1
        for group in GROUPS:
            self.kinds.set_label(
                group,
                strings.SEARCH_KIND_TAB.format(
                    label=strings.SEARCH_KINDS[group], n=local_digits(counts[group])
                ),
            )
        arrow = "←" if strings.RTL else "→"  # points from the typo to the correction
        pairs = strings.LIST_SEPARATOR.join(
            f"{bad} {arrow} {good}" for bad, good in result.corrections.items()
        )
        self.corrections.setText(strings.SEARCH_CORRECTED.format(pairs=pairs) if pairs else "")
        self.corrections.setVisible(bool(pairs))
        more = 0 if self.in_content() else result.more_in_content
        self.more.setText(strings.SEARCH_MORE_IN_CONTENT.format(n=local_digits(more)))
        self.more.setVisible(more > 0)
        self._render()

    def _render(self) -> None:
        """The hits of the chosen tab."""
        result = self._result
        group = self.kinds.choice()
        hits = [h for h in result.hits if group == ALL or KIND_GROUPS.get(h.kind) == group]
        terms = query_terms(result.query) + list(result.corrections.values())
        self.results.setUpdatesEnabled(False)
        self.results.clear()
        for hit in hits:
            item = QListWidgetItem()
            item.setData(HIT_ROLE, hit)
            widget = HitWidget(hit, terms)
            self.results.addItem(item)
            self.results.setItemWidget(item, widget)
            item.setSizeHint(QSize(0, widget.row_height(self.font())))
        self.results.setUpdatesEnabled(True)
        if self.results.count():
            self.results.setCurrentRow(0)
        self.results.setVisible(bool(hits))
        self.empty.setText(strings.SEARCH_EMPTY_KIND if result.hits else strings.SEARCH_EMPTY)
        self.empty.setVisible(not hits)

    def scope(self) -> ArchiveScope:
        return self.scope_switch.scope()

    def in_content(self) -> bool:
        return self.content.isChecked()

    def reset_scope(self) -> None:
        """Every switch back to its default, for the next search."""
        self.scope_switch.set_scope(ArchiveScope.ACTIVE)
        self.content.blockSignals(True)
        self.content.setChecked(False)
        self.content.blockSignals(False)
        self.kinds.set_choice(ALL)

    def open_current(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self._activate(item)

    def _activate(self, item: QListWidgetItem) -> None:
        self.open_hit.emit(item.data(HIT_ROLE))
