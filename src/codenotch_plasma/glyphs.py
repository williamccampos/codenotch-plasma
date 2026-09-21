"""Provider marks: PNG assets where available, traced vectors as fallback."""

import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPainterPath, QPixmap, QTransform

_ASSETS = Path(__file__).with_name("assets")
_DATA = json.loads((Path(__file__).with_name("glyphs.json")).read_text())
_EXTRA_OUTLINES = {
    "cursor": [
        [0.50, 0.10, 0.84, 0.28, 0.50, 0.46, 0.16, 0.28],
        [0.16, 0.28, 0.50, 0.46, 0.50, 0.86, 0.16, 0.68],
        [0.50, 0.46, 0.84, 0.28, 0.84, 0.68, 0.50, 0.86],
    ],
}
GLYPH_SCALE = {**_DATA["scale"], "cursor": 0.92, "kiro": 0.95}
OUTLINES = {**_DATA["outlines"], **_EXTRA_OUTLINES}
_ASSET_CACHE = {}


def _load_asset(name):
    if name in _ASSET_CACHE:
        return _ASSET_CACHE[name]
    path = _ASSETS / f"{name}.png"
    if not path.exists():
        _ASSET_CACHE[name] = None
        return None
    pix = QPixmap(str(path))
    _ASSET_CACHE[name] = pix if not pix.isNull() else None
    return _ASSET_CACHE[name]


def glyph_path(name, cx, cy, size):
    polys = OUTLINES.get(name)
    if not polys:
        return QPainterPath()
    s = size * GLYPH_SCALE.get(name, 1)
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for poly in polys:
        sub = QPainterPath()
        for i in range(0, len(poly), 2):
            if i == 0:
                sub.moveTo(poly[i], poly[i + 1])
            else:
                sub.lineTo(poly[i], poly[i + 1])
        sub.closeSubpath()
        path.addPath(sub)
    t = QTransform()
    t.translate(cx - s / 2, cy - s / 2)
    t.scale(s, s)
    return t.map(path)


def draw_glyph(painter, name, cx, cy, size, alpha=1.0, badge=None):
    painter.save()
    color = QColor(255, 255, 255, int(255 * max(0.0, min(1.0, alpha))))
    pix = _load_asset(name)
    if pix is not None:
        target = int(size * GLYPH_SCALE.get(name, 1))
        scaled = pix.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = int(cx - scaled.width() / 2)
        y = int(cy - scaled.height() / 2)
        painter.setOpacity(alpha)
        painter.drawPixmap(x, y, scaled)
    else:
        path = glyph_path(name, cx, cy, size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        if not path.isEmpty():
            painter.drawPath(path)
        else:
            font = QFont("Noto Sans")
            font.setPixelSize(max(10, int(size * 0.55)))
            font.setWeight(QFont.Bold)
            painter.setFont(font)
            painter.setPen(color)
            letter = name[:1].upper()
            metrics = painter.fontMetrics()
            painter.drawText(
                int(cx - metrics.horizontalAdvance(letter) / 2),
                int(cy + metrics.ascent() / 3),
                letter,
            )
    if badge == "corp":
        r = max(5, int(size * 0.14))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#00FF88"))
        painter.drawEllipse(int(cx + size * 0.18), int(cy - size * 0.30), r, r)
        painter.setPen(QColor("#000000"))
        font = QFont("Noto Sans")
        font.setPixelSize(max(7, r))
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        painter.drawText(
            int(cx + size * 0.18 + (r - metrics.horizontalAdvance("C")) / 2),
            int(cy - size * 0.30 + r - metrics.descent() / 2),
            "C",
        )
    elif badge == "personal":
        r = max(5, int(size * 0.14))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(cx + size * 0.18), int(cy - size * 0.30), r, r)
        painter.setPen(QColor("#000000"))
        font = QFont("Noto Sans")
        font.setPixelSize(max(7, r))
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        painter.drawText(
            int(cx + size * 0.18 + (r - metrics.horizontalAdvance("P")) / 2),
            int(cy - size * 0.30 + r - metrics.descent() / 2),
            "P",
        )
    painter.restore()
