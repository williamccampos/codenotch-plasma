"""App and tray icons for Codenotch."""

import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QImage, QPixmap

from .theme import normalize_mode, resolve_dark

_ICON_NAME = "codenotch-plasma"
_LAUNCHER_ICON_NAME = "codenotch"
_SVG_FILL = "#FFFFFF"
_ICON_FILL_DARK = "#FFFFFF"
_ICON_FILL_LIGHT = "#000000"
_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)
_USER_ICON_ROOT = Path.home() / ".local/share/icons/hicolor"
_SYSTEM_ICON_ROOT = Path("/usr/share/icons/hicolor")
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
        yield _SYSTEM_ICON_ROOT / f"{size}x{size}" / "apps" / f"{_ICON_NAME}.png"


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
    """Tray and launcher icons stay white; only the notch body changes theme."""
    return _ICON_FILL_DARK


def _system_icon_path(size: int) -> Path | None:
    path = _SYSTEM_ICON_ROOT / f"{size}x{size}" / "apps" / f"{_ICON_NAME}.png"
    return path if path.exists() else None


def _pixmap_for_fill(size: int, fill: str) -> QPixmap | None:
    source = _system_icon_path(size)
    if source is None:
        bundled = Path(__file__).resolve().parent / "assets" / f"{_ICON_NAME}.png"
        if bundled.exists():
            source = bundled
        else:
            return None

    pixmap = QPixmap(str(source))
    if pixmap.isNull():
        return None
    if pixmap.width() != size or pixmap.height() != size:
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    if fill == _ICON_FILL_DARK:
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        image.invertPixels(QImage.InvertRgb)
        return QPixmap.fromImage(image)
    return pixmap


def render_app_icon(size=32, fill=None):
    pixmap = _pixmap_for_fill(size, fill or icon_fill_for_theme())
    if pixmap is not None and not pixmap.isNull():
        return pixmap

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
    if _SYSTEM_ICON_ROOT.exists():
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-q", str(_SYSTEM_ICON_ROOT)],
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

    wrote = False
    for size in _ICON_SIZES:
        pixmap = _pixmap_for_fill(size, fill)
        if pixmap is None or pixmap.isNull():
            continue
        out_dir = _USER_ICON_ROOT / f"{size}x{size}" / "apps"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in (_ICON_NAME, _LAUNCHER_ICON_NAME):
            pixmap.save(str(out_dir / f"{name}.png"), "PNG")
        wrote = True

    svg = _master_svg()
    if svg is not None:
        svg_text = svg.read_text(encoding="utf-8").replace(
            f'fill="{_SVG_FILL}"', f'fill="{fill}"',
        )
        scalable_dir = _USER_ICON_ROOT / "scalable" / "apps"
        scalable_dir.mkdir(parents=True, exist_ok=True)
        for name in (_ICON_NAME, _LAUNCHER_ICON_NAME):
            (scalable_dir / f"{name}.svg").write_text(svg_text, encoding="utf-8")
        wrote = True

    if wrote:
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
    fill = icon_fill_for_theme()
    if not for_tray:
        return QIcon(render_app_icon(size, fill=fill))

    icon = QIcon()
    for px in (16, 22, 24, 32):
        pixmap = render_app_icon(px, fill=fill)
        if pixmap is not None and not pixmap.isNull():
            icon.addPixmap(pixmap)
    return icon
