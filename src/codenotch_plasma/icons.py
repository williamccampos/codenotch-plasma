"""App and tray icons for Codenotch."""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QImage, QPixmap

_ICON_NAME = "codenotch-plasma"
_SVG_FILL = "#FFFFFF"


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


def _fill_color():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return "#E8E8E8"
    return app.palette().windowText().color().name()


def _svg_png(svg_path: Path, size: int, fill: str) -> bytes | None:
    try:
        import cairosvg

        svg_text = svg_path.read_text(encoding="utf-8").replace(
            f'fill="{_SVG_FILL}"',
            f'fill="{fill}"',
        )
        return cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            output_width=size,
            output_height=size,
            background_color="transparent",
        )
    except Exception:
        return None


def render_app_icon(size=32, fill=None):
    svg = _master_svg()
    if svg:
        data = _svg_png(svg, size, fill or _fill_color())
        if data:
            image = QImage.fromData(data)
            if not image.isNull():
                return QPixmap.fromImage(image)

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


def load_app_icon(size=32, for_tray=False):
    if for_tray:
        return QIcon(render_app_icon(size))

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
