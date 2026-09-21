"""Theme toggle glyphs — Lucide sun/moon (ISC), 24×24 viewBox."""

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPainterPath, QPen

# https://github.com/lucide-icons/lucide/blob/main/icons/sun.svg
_SUN_LINES = (
    (12, 2, 12, 4),
    (12, 20, 12, 22),
    (2, 12, 4, 12),
    (20, 12, 22, 12),
    (4.93, 4.93, 6.34, 6.34),
    (17.66, 17.66, 19.07, 19.07),
    (19.07, 4.93, 17.66, 6.34),
    (6.34, 17.66, 4.93, 19.07),
)
_SUN_CIRCLE = (12, 12, 4)


def _map_point(cx, cy, scale, x, y):
    return QPointF(cx + (x - 12) * scale, cy + (y - 12) * scale)


def draw_theme_icon(painter, kind, cx, cy, size, color):
    """Draw a bold Lucide-style sun or moon centered at (cx, cy)."""
    scale = size / 24.0
    stroke = max(2.6, size * 0.115)
    icon = QColor(color)
    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(icon, stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    if kind == "sun":
        sx, sy, radius = _SUN_CIRCLE
        painter.drawEllipse(_map_point(cx, cy, scale, sx, sy), radius * scale, radius * scale)
        for x1, y1, x2, y2 in _SUN_LINES:
            painter.drawLine(_map_point(cx, cy, scale, x1, y1), _map_point(cx, cy, scale, x2, y2))
    else:
        # Filled crescent inspired by Lucide/Material dark_mode — reads better small.
        radius = 8.6 * scale
        body = QPainterPath()
        body.addEllipse(QPointF(cx - 0.6 * scale, cy), radius, radius)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + 4.8 * scale, cy - 0.2 * scale), radius * 0.92, radius * 0.92)
        crescent = body.subtracted(cut)
        painter.setPen(Qt.NoPen)
        painter.setBrush(icon)
        painter.drawPath(crescent)

    painter.restore()
