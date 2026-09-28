"""Transport icons painted at runtime in the current text colour (crisp at any DPI, both themes)."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

ICON_SIZE = 20
_SCALE = 3  # paint oversampled; Qt scales down per screen


def _canvas() -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(ICON_SIZE * _SCALE, ICON_SIZE * _SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_SCALE, _SCALE)
    return pixmap, painter


def play_icon(color: QColor) -> QIcon:
    pixmap, p = _canvas()
    path = QPainterPath(QPointF(6, 3.5))
    path.lineTo(17, 10)
    path.lineTo(6, 16.5)
    path.closeSubpath()
    p.setPen(
        QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    p.setBrush(color)
    p.drawPath(path)
    p.end()
    return QIcon(pixmap)


def pause_icon(color: QColor) -> QIcon:
    pixmap, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(5, 3.5, 3.6, 13), 1.2, 1.2)
    p.drawRoundedRect(QRectF(11.4, 3.5, 3.6, 13), 1.2, 1.2)
    p.end()
    return QIcon(pixmap)


def skip_icon(color: QColor, forward: bool, label: str = "10") -> QIcon:
    """Circular arrow with the skip amount inside; `forward` turns clockwise."""
    pixmap, p = _canvas()
    center, radius = QPointF(10, 10.5), 7.2
    pen = QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    # Gap at the top; the arrow head sits at the end of the arc.
    start, span = (60, 290) if not forward else (120, -290)
    p.drawArc(rect, start * 16, span * 16)
    angle = math.radians(start)
    tip = QPointF(center.x() + radius * math.cos(angle), center.y() - radius * math.sin(angle))
    direction = -1 if forward else 1
    head = QPainterPath(tip + QPointF(direction * 3.2, 0))
    head.lineTo(tip + QPointF(-direction * 0.6, -2.6))
    head.lineTo(tip + QPointF(-direction * 0.6, 2.6))
    head.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(head)
    font = QFont()
    font.setPixelSize(7)
    font.setBold(True)
    p.setFont(font)
    p.setPen(color)
    p.drawText(rect.adjusted(0, 1, 0, 0), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return QIcon(pixmap)


def silence_icon(color: QColor) -> QIcon:
    """Two runs of waveform bars with arrows squeezing out the pause between them."""
    pixmap, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for x, height in ((1.6, 6.0), (4.2, 11.0), (14.2, 9.0), (16.8, 5.0)):
        p.drawRoundedRect(QRectF(x, 10 - height / 2, 1.7, height), 0.85, 0.85)
    p.setPen(
        QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    for tip, back in ((9.0, 7.3), (11.0, 12.7)):
        arrow = QPainterPath(QPointF(back, 7.6))
        arrow.lineTo(tip, 10)
        arrow.lineTo(back, 12.4)
        p.drawPath(arrow)
    p.end()
    return QIcon(pixmap)
