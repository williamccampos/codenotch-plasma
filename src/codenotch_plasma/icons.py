"""App and tray icons for Codenotch."""

import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QImage, QPixmap

from .theme import normalize_mode, resolve_dark

_ICON_NAME = "codenotch-plasma"
_SVG_FILL = "#FFFFFF"
_ICON_FILL_DARK = "#FFFFFF"
_ICON_FILL_LIGHT = "#000000"
_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)
_USER_ICON_ROOT = Path.home() / ".local/share/icons/hicolor"
_last_sync_fill = None
_active_mode = "auto"


def set_theme_mode(mode):
    global _active_mode
    _active_mode = normalize_mode(mode)


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
    for size in _ICON_SIZES:
        yield _USER_ICON_ROOT / f"{size}x{size}" / "apps" / f"{_ICON_NAME}.png"
        yield Path(f"/usr/share/icons/hicolor/{size}x{size}/apps/{_ICON_NAME}.png")


def _master_svg():
    for path in _search_paths():
        if path.suffix == ".svg" and path.exists():
            return path
    return None


def is_dark_theme():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return True
    return app.palette().window().color().lightness() < 128


def icon_fill_for_theme():
    dark = resolve_dark(_active_mode, is_dark_theme())
    return _ICON_FILL_DARK if dark else _ICON_FILL_LIGHT


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
        data = _svg_png(svg, size, fill or icon_fill_for_theme())
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


def refresh_system_icon_cache():
    cache = Path.home() / ".cache/icon-cache.kcache"
    if cache.exists():
        cache.unlink()
    for pattern in ("ksycoca5_*", "ksycoca6_*"):
        for path in Path.home().joinpath(".cache").glob(pattern):
            path.unlink(missing_ok=True)
    if _USER_ICON_ROOT.exists():
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-q", str(_USER_ICON_ROOT)],
            check=False,
            capture_output=True,
        )
    for cmd in ("kbuildsycoca6", "kbuildsycoca5"):
        path = shutil.which(cmd)
        if path:
            subprocess.run([path, "--noincremental"], check=False, capture_output=True)


def sync_system_icons(force=False):
    """Write theme-aware icons to the user hicolor theme."""
    global _last_sync_fill

    fill = icon_fill_for_theme()
    if not force and fill == _last_sync_fill:
        return fill

    svg = _master_svg()
    if svg is None:
        return fill

    for size in _ICON_SIZES:
        out = _USER_ICON_ROOT / f"{size}x{size}" / "apps" / f"{_ICON_NAME}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        data = _svg_png(svg, size, fill)
        if data:
            out.write_bytes(data)

    scalable = _USER_ICON_ROOT / "scalable" / "apps" / f"{_ICON_NAME}.svg"
    scalable.parent.mkdir(parents=True, exist_ok=True)
    scalable.write_text(
        svg.read_text(encoding="utf-8").replace(f'fill="{_SVG_FILL}"', f'fill="{fill}"'),
        encoding="utf-8",
    )

    _last_sync_fill = fill
    refresh_system_icon_cache()
    return fill


def install_theme_listener(callback):
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.paletteChanged.connect(callback)

    try:
        from PyQt5.QtDBus import QDBusConnection

        bus = QDBusConnection.sessionBus()
        bus.connect(
            "",
            "/KGlobalSettings",
            "org.kde.KGlobalSettings",
            "notifyChange",
            callback,
        )
    except Exception:
        pass


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
