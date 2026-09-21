"""Navigation and chrome icons, painted at runtime in the current text colour.

Same approach as `ui/player/icons.py`: no image assets, crisp at any DPI, correct in
both themes. Callers repaint on QEvent.Type.PaletteChange.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

NAV_ICON_SIZE = 18
_SCALE = 3


def _canvas(size: int = NAV_ICON_SIZE) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_SCALE, _SCALE)
    return pixmap, painter


def _stroke(painter: QPainter, color: QColor, width: float = 1.4) -> None:
    painter.setPen(
        QPen(
            color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)


def episodes_icon(color: QColor) -> QIcon:
    """Stacked cards: the episode list."""
    pixmap, p = _canvas()
    _stroke(p, color)
    p.drawRoundedRect(QRectF(2.5, 5.5, 13, 10), 2, 2)
    p.drawLine(QPointF(4.5, 3.5), QPointF(13.5, 3.5))
    p.drawLine(QPointF(5.5, 9), QPointF(12.5, 9))
    p.drawLine(QPointF(5.5, 12), QPointF(10.5, 12))
    p.end()
    return QIcon(pixmap)


def board_icon(color: QColor) -> QIcon:
    """Three kanban columns."""
    pixmap, p = _canvas()
    _stroke(p, color)
    p.drawRoundedRect(QRectF(2.5, 3.5, 3.6, 11), 1.2, 1.2)
    p.drawRoundedRect(QRectF(7.2, 3.5, 3.6, 7.5), 1.2, 1.2)
    p.drawRoundedRect(QRectF(11.9, 3.5, 3.6, 9), 1.2, 1.2)
    p.end()
    return QIcon(pixmap)


def voices_icon(color: QColor) -> QIcon:
    """A waveform: five bars of different heights."""
    pixmap, p = _canvas()
    _stroke(p, color, 1.6)
    for x, half in ((3.2, 2.2), (6.1, 5.0), (9.0, 6.6), (11.9, 4.0), (14.8, 1.8)):
        p.drawLine(QPointF(x, 9 - half), QPointF(x, 9 + half))
    p.end()
    return QIcon(pixmap)


def ideas_icon(color: QColor) -> QIcon:
    """A lamp: the idea inbox."""
    pixmap, p = _canvas()
    _stroke(p, color)
    p.drawArc(QRectF(4, 2, 10, 10), 0, 180 * 16)
    p.drawLine(QPointF(4, 7), QPointF(6.3, 11.2))
    p.drawLine(QPointF(14, 7), QPointF(11.7, 11.2))
    p.drawLine(QPointF(6.3, 11.6), QPointF(11.7, 11.6))
    p.drawLine(QPointF(7.2, 14.2), QPointF(10.8, 14.2))
    p.end()
    return QIcon(pixmap)


def tags_icon(color: QColor) -> QIcon:
    """A luggage tag with its hole."""
    pixmap, p = _canvas()
    _stroke(p, color)
    path = QPainterPath(QPointF(8.6, 2.6))
    path.lineTo(15.2, 9.2)
    path.lineTo(9.2, 15.2)
    path.lineTo(2.6, 8.6)
    path.lineTo(2.6, 2.6)
    path.closeSubpath()
    p.drawPath(path)
    p.drawEllipse(QPointF(5.6, 5.6), 1.3, 1.3)
    p.end()
    return QIcon(pixmap)


def settings_icon(color: QColor) -> QIcon:
    """Two sliders."""
    pixmap, p = _canvas()
    _stroke(p, color)
    p.drawLine(QPointF(3, 6.2), QPointF(15, 6.2))
    p.drawLine(QPointF(3, 11.8), QPointF(15, 11.8))
    p.setBrush(color)
    p.drawEllipse(QPointF(11.4, 6.2), 1.9, 1.9)
    p.drawEllipse(QPointF(6.6, 11.8), 1.9, 1.9)
    p.end()
    return QIcon(pixmap)


def theme_icon(color: QColor, dark: bool) -> QIcon:
    """A moon when the next theme is dark, a sun when it is light."""
    pixmap, p = _canvas()
    _stroke(p, color)
    if dark:
        # A crescent is a disc with a second, offset disc taken out of it. Building it
        # that way (rather than from two hand-tuned arcs) keeps both horns sharp and the
        # inner curve a true circle, which is what makes it read as the moon.
        disc = QPainterPath()
        disc.addEllipse(QPointF(8.6, 9.4), 6.6, 6.6)
        bite = QPainterPath()
        bite.addEllipse(QPointF(12.4, 5.9), 5.6, 5.6)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(disc.subtracted(bite))
    else:
        p.setBrush(color)
        p.drawEllipse(QPointF(9, 9), 3.4, 3.4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        _stroke(p, color, 1.3)
        for dx, dy in ((0, 1), (1, 0), (0.7, 0.7), (-0.7, 0.7)):
            p.drawLine(QPointF(9 + dx * 5.4, 9 + dy * 5.4), QPointF(9 + dx * 7.0, 9 + dy * 7.0))
            p.drawLine(QPointF(9 - dx * 5.4, 9 - dy * 5.4), QPointF(9 - dx * 7.0, 9 - dy * 7.0))
    p.end()
    return QIcon(pixmap)


def history_icon(color: QColor, forward: bool) -> QIcon:
    """A curved arrow: back for undo, forward (mirrored) for redo.

    Both are drawn in the app's own direction-free way — the arrow points at the
    direction of the action, not of the script.
    """
    pixmap, p = _canvas()
    _stroke(p, color, 1.5)
    if forward:
        p.translate(NAV_ICON_SIZE, 0)
        p.scale(-1, 1)
    path = QPainterPath(QPointF(5.5, 5.4))
    path.lineTo(2.6, 8.3)  # arrow head, upper barb
    path.lineTo(5.5, 11.2)
    p.drawPath(path)
    tail = QPainterPath(QPointF(2.8, 8.3))
    tail.lineTo(10.2, 8.3)
    tail.arcTo(QRectF(10.2, 8.3, 4.6, 4.6), 90, -180)  # loop down and back
    tail.lineTo(7.4, 12.9)
    p.drawPath(tail)
    p.end()
    return QIcon(pixmap)


def back_icon(color: QColor, rtl: bool = True) -> QIcon:
    """A plain arrow for "the page before".

    It points against the reading direction — right in Persian, left in English; the
    curved `history_icon` is undo's, and the two must not be mistaken for each other.
    """
    pixmap, p = _canvas()
    _stroke(p, color, 1.5)
    if not rtl:
        p.translate(NAV_ICON_SIZE, 0)
        p.scale(-1, 1)
    p.drawLine(QPointF(3.4, 9), QPointF(14.6, 9))
    path = QPainterPath(QPointF(10.4, 4.8))
    path.lineTo(14.8, 9)
    path.lineTo(10.4, 13.2)
    p.drawPath(path)
    p.end()
    return QIcon(pixmap)


def search_icon(color: QColor) -> QIcon:
    pixmap, p = _canvas()
    _stroke(p, color, 1.5)
    p.drawEllipse(QPointF(8, 7.8), 4.6, 4.6)
    p.drawLine(QPointF(11.5, 11.3), QPointF(15, 14.8))
    p.end()
    return QIcon(pixmap)


def sidebar_icon(color: QColor, rtl: bool, collapse: bool) -> QIcon:
    """A window with its side rail, and a chevron saying which way the rail will move."""
    pixmap, p = _canvas()
    _stroke(p, color, 1.4)
    if rtl:  # the rail sits on the right in RTL; draw for LTR and mirror
        p.translate(NAV_ICON_SIZE, 0)
        p.scale(-1, 1)
    p.drawRoundedRect(QRectF(2.5, 3.5, 13, 11), 2, 2)
    p.drawLine(QPointF(7, 3.5), QPointF(7, 14.5))
    # collapse: the chevron points into the rail (it shrinks); expand: out of it
    tip, back = (9.6, 12.2) if collapse else (12.2, 9.6)
    path = QPainterPath(QPointF(back, 6.6))
    path.lineTo(tip, 9)
    path.lineTo(back, 11.4)
    p.drawPath(path)
    p.end()
    return QIcon(pixmap)


def list_pane_icon(color: QColor, rtl: bool, hidden: bool) -> QIcon:
    """Two panes side by side; the list pane is filled when it is showing."""
    pixmap, p = _canvas()
    _stroke(p, color, 1.4)
    if rtl:
        p.translate(NAV_ICON_SIZE, 0)
        p.scale(-1, 1)
    p.drawRoundedRect(QRectF(2.5, 3.5, 13, 11), 2, 2)
    p.drawLine(QPointF(7.5, 3.5), QPointF(7.5, 14.5))
    if not hidden:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(3.6, 4.6, 2.8, 8.8), 0.8, 0.8)
    else:
        for y in (6.6, 9, 11.4):
            p.drawLine(QPointF(4.3, y), QPointF(5.7, y))
    p.end()
    return QIcon(pixmap)


def more_icon(color: QColor) -> QIcon:
    """Three dots in a row: "more actions"."""
    pixmap, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for x in (4.2, 9, 13.8):
        p.drawEllipse(QPointF(x, 9), 1.45, 1.45)
    p.end()
    return QIcon(pixmap)
