"""App and tray icons for Codenotch."""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QImage, QPixmap

_ICON_NAME = "codenotch-plasma"


def _search_paths():
    here = Path(__file__).resolve().parent
    roots = (
        here / "assets",
        Path("/usr/share/codenotch-plasma/icons"),
        Path.home() / ".local/share/codenotch-plasma/icons",
    )
    for root in roots:
        yield root / f"{_ICON_NAME}.svg"
        yield root / f"{_ICON_NAME}.png"
    for size in (256, 128, 64, 48, 32, 24, 22, 16):
        yield Path(f"/usr/share/icons/hicolor/{size}x{size}/apps/{_ICON_NAME}.png")


def _master_svg():
    for path in _search_paths():
        if path.suffix == ".svg" and path.exists():
            return path
    return None


def render_app_icon(size=32):
    svg = _master_svg()
    if svg:
        try:
            import cairosvg

            data = cairosvg.svg2png(
                url=str(svg),
                output_width=size,
                output_height=size,
                background_color="transparent",
            )
            image = QImage.fromData(data)
            if not image.isNull():
                return QPixmap.fromImage(image)
        except Exception:
            pass

    bundled = Path(__file__).resolve().parent / "assets" / f"{_ICON_NAME}.png"
    if bundled.exists():
        pixmap = QPixmap(str(bundled))
        if not pixmap.isNull():
            return pixmap.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    return pixmap


def load_app_icon(size=32):
    themed = QIcon.fromTheme(_ICON_NAME)
    if not themed.isNull():
        pixmap = themed.pixmap(size, size)
        if not pixmap.isNull():
            return QIcon(pixmap)

    for path in _search_paths():
        if path.suffix == ".png" and path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon

    return QIcon(render_app_icon(size))
