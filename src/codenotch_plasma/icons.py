"""App and tray icons for Codenotch."""

from pathlib import Path

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_ICON_NAME = "codenotch-plasma"
_RING_COLORS = ("#00FF88", "#F2FF00", "#00D4FF")


def _search_paths():
    here = Path(__file__).resolve().parent
    roots = (
        here / "assets",
        Path("/usr/share/codenotch-plasma/icons"),
        Path.home() / ".local/share/codenotch-plasma/icons",
    )
    for root in roots:
        yield root / f"{_ICON_NAME}.png"
        yield root / f"{_ICON_NAME}.svg"
    for size in (256, 128, 64, 48, 32, 24, 22, 16):
        yield Path(f"/usr/share/icons/hicolor/{size}x{size}/apps/{_ICON_NAME}.png")


def render_app_icon(size=32):
    """Draw the notch pill with three usage rings."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.12
    height = size - 2 * margin
    width = max(size * 0.34, 6)
    x = (size - width) / 2
    y = margin

    if size >= 48:
        painter.setBrush(QColor("#2A2A2A"))
        painter.setPen(Qt.NoPen)
        bg = size * 0.08
        painter.drawRoundedRect(
            QRectF(bg, bg, size - 2 * bg, size - 2 * bg),
            size * 0.22,
            size * 0.22,
        )

    painter.setBrush(QColor("#101010"))
    painter.setPen(QPen(QColor("#3A3A3A"), max(1, size / 32)))
    painter.drawRoundedRect(QRectF(x, y, width, height), width / 2, width / 2)

    ring_size = min(width * 1.35, height / 3.8)
    stroke = max(1.5, size / 14)
    centers = (
        y + height * 0.24,
        y + height * 0.50,
        y + height * 0.76,
    )
    for index, cy in enumerate(centers):
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(_RING_COLORS[index]), stroke, Qt.SolidLine, Qt.RoundCap))
        inset = (width - ring_size) / 2
        rect = QRectF(x + inset, cy - ring_size / 2, ring_size, ring_size)
        painter.drawArc(rect, 35 * 16, 290 * 16)

    painter.end()
    return pix


def load_app_icon(size=32):
    themed = QIcon.fromTheme(_ICON_NAME)
    if not themed.isNull():
        pixmap = themed.pixmap(size, size)
        if not pixmap.isNull():
            return QIcon(pixmap)

    for path in _search_paths():
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon

    return QIcon(render_app_icon(size))
