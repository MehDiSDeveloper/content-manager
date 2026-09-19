"""Waveform with playhead, played/unplayed colouring, note markers, click/drag seeking.

Always left-to-right (media timelines are not mirrored in RTL UIs).
"""

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from podcast_workspace.audio.waveform import Waveform
from podcast_workspace.ui.support import format_clock

BAR_WIDTH = 2.0
BAR_GAP = 1.0
PAD_X = 10
PAD_Y = 12
MARKER_ZONE = 8
LOUDNESS_PERCENTILE = 99.5
GAMMA = 0.75  # lifts quiet speech so it stays visible next to loud peaks


class WaveformView(QWidget):
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._waveform: Waveform | None = None
        self._norm = 1.0
        self._duration = 0
        self._position = 0
        self._markers: list[tuple[int, int]] = []
        self._active: frozenset[int] = frozenset()
        self._hover_x: float | None = None
        self._drag_ms: int | None = None
        self._path: QPainterPath | None = None
        self._message = ""

    def sizeHint(self) -> QSize:
        return QSize(600, 112)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 112)

    # data -------------------------------------------------------------------------------
    def set_waveform(self, waveform: Waveform | None) -> None:
        self._waveform = waveform
        if waveform is not None and waveform.buckets:
            loud = float(np.percentile(waveform.peaks[:, 0], LOUDNESS_PERCENTILE))
            self._norm = max(loud, 1e-3)
            if waveform.complete or self._duration <= 0:
                self._duration = max(self._duration, waveform.duration_ms)
        self._path = None
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        if duration_ms != self._duration:
            self._duration = duration_ms
            self._path = None
            self.update()

    def set_position(self, position_ms: int) -> None:
        if self._drag_ms is None and position_ms != self._position:
            old = self._x_for(self._position)
            self._position = position_ms
            new = self._x_for(position_ms)
            left, right = min(old, new) - 3, max(old, new) + 3
            self.update(int(left), 0, int(right - left) + 1, self.height())

    def set_markers(self, markers: list[tuple[int, int]]) -> None:
        """(note_id, position_ms) pairs."""
        self._markers = markers
        self.update()

    def set_active(self, active: frozenset[int]) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    # geometry ---------------------------------------------------------------------------
    def _plot(self) -> QRectF:
        return QRectF(
            PAD_X, PAD_Y, self.width() - 2 * PAD_X, self.height() - 2 * PAD_Y - MARKER_ZONE
        )

    def _x_for(self, ms: int) -> float:
        plot = self._plot()
        if self._duration <= 0:
            return plot.left()
        return plot.left() + plot.width() * min(1.0, max(0.0, ms / self._duration))

    def _ms_for(self, x: float) -> int:
        plot = self._plot()
        frac = (x - plot.left()) / max(1.0, plot.width())
        return round(min(1.0, max(0.0, frac)) * self._duration)

    def _build_path(self) -> QPainterPath:
        path = QPainterPath()
        waveform = self._waveform
        plot = self._plot()
        if waveform is None or not waveform.buckets or self._duration <= 0:
            return path
        step = BAR_WIDTH + BAR_GAP
        columns = max(1, int(plot.width() // step))
        ms_per_column = self._duration / columns
        edges = (np.arange(columns + 1) * ms_per_column / waveform.bucket_ms).astype(np.int64)
        edges = np.clip(edges, 0, waveform.buckets)
        have = edges[:-1] < edges[1:]
        starts = np.minimum(edges[:-1], waveform.buckets - 1)
        heights = np.maximum.reduceat(waveform.peaks[:, 0], starts)
        heights = np.where(have, heights, 0.0)
        heights = np.clip(heights / self._norm, 0.0, 1.0) ** GAMMA
        mid = plot.center().y()
        half = plot.height() / 2
        for i in np.nonzero(have)[0]:
            h = max(1.0, float(heights[i]) * half)
            x = plot.left() + i * step
            path.addRoundedRect(QRectF(x, mid - h, BAR_WIDTH, 2 * h), 1.0, 1.0)
        return path

    # painting ---------------------------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        accent = palette.color(QPalette.ColorRole.Highlight)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        text = palette.color(QPalette.ColorRole.Text)
        rest = QColor(muted)
        rest.setAlphaF(0.45)

        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        border = QColor(muted)
        border.setAlphaF(0.35)
        focused = self.hasFocus()
        painter.setPen(QPen(accent if focused else border, 1.5 if focused else 1))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(frame, 8, 8)

        plot = self._plot()
        if self._path is None:
            self._path = self._build_path()
        if self._path.isEmpty():
            painter.setPen(QPen(rest, 1))
            painter.drawLine(
                QPointF(plot.left(), plot.center().y()), QPointF(plot.right(), plot.center().y())
            )
            if self._message:
                painter.setPen(muted)
                painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._message)
        shown = self._drag_ms if self._drag_ms is not None else self._position
        cursor_x = self._x_for(shown)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rest)
        painter.drawPath(self._path)
        painter.save()
        painter.setClipRect(QRectF(0, 0, cursor_x, self.height()))
        painter.setBrush(accent)
        painter.drawPath(self._path)
        painter.restore()

        # note markers under the plot
        base_y = plot.bottom() + MARKER_ZONE - 1
        for note_id, position in self._markers:
            x = self._x_for(position)
            active = note_id in self._active
            painter.setBrush(accent if active else muted)
            size = 5.0 if active else 3.5
            tri = QPainterPath(QPointF(x, base_y - size * 1.6))
            tri.lineTo(x - size, base_y)
            tri.lineTo(x + size, base_y)
            tri.closeSubpath()
            painter.drawPath(tri)

        # playhead
        painter.setPen(QPen(text, 1.5))
        painter.drawLine(QPointF(cursor_x, plot.top() - 4), QPointF(cursor_x, plot.bottom() + 2))

        # hover time
        if self._hover_x is not None and self._duration > 0:
            hover_ms = self._ms_for(self._hover_x)
            painter.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(self._hover_x, plot.top()), QPointF(self._hover_x, plot.bottom())
            )
            label = format_clock(hover_ms)
            metrics = painter.fontMetrics()
            w = metrics.horizontalAdvance(label) + 10
            h = metrics.height() + 2
            x = min(max(self._hover_x - w / 2, 2), self.width() - w - 2)
            box = QRectF(x, 1, w, h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color(QPalette.ColorRole.Window))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(text)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

    # interaction ------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._drag_ms = self._ms_for(event.position().x())
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover_x = event.position().x()
        if self._drag_ms is not None:
            self._drag_ms = self._ms_for(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_ms is not None:
            target = self._drag_ms
            self._drag_ms = None
            self._position = target
            self.seek_requested.emit(target)
            self.update()

    def leaveEvent(self, event: QEvent) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._path = None
        super().resizeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self.update()
        super().changeEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusOutEvent(event)
