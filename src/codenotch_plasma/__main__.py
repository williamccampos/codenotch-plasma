import json
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction

from .layout import configure_layout, set_appearance
from .overlay import NotchOverlay
from .providers import discover_providers
from .store import UsageStore


CONFIG_PATH = Path.home() / ".config" / "codenotch-plasma" / "config.json"


class DemoProvider:
    tracks_sessions = False
    backoff_until = None

    def __init__(self, pid, name, glyph, fraction, label, manage_url):
        self.id = pid
        self.display_name = name
        self.glyph = glyph
        self.manage_url = manage_url
        self._fraction = fraction
        self._label = label

    def available(self):
        return True

    def fetch(self, _previous=None):
        from datetime import datetime, timedelta, timezone
        return {
            "windows": [{
                "id": "primary",
                "label": self._label,
                "usedFraction": self._fraction,
                "resetsAt": datetime.now(timezone.utc) + timedelta(days=14),
            }],
            "headlineID": "primary",
        }


def load_config():
    defaults = {
        "edge": "right",
        "position": 0.5,
        "alwaysOpen": False,
        "hideInFullscreen": True,
        "scale": 1.0,
        "textScale": 1.0,
        "showLabels": True,
        "hotZone": 4,
        "openDelay": 150,
        "refreshInterval": 60,
        "color": "#000000",
        "opacity": 1.0,
        "disabledProviders": [],
    }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults.update(data)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def apply_config(config):
    configure_layout(
        scale=float(config.get("scale", 1)),
        show_labels=bool(config.get("showLabels", True)),
        text_scale=float(config.get("textScale", 1)),
    )
    set_appearance(config.get("color", "#000000"), float(config.get("opacity", 1)))


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName("Codenotch")
    app.setQuitOnLastWindowClosed(False)

    config = load_config()
    apply_config(config)
    providers = discover_providers(disabled=config.get("disabledProviders"))
    if not providers:
        providers = [
            DemoProvider("demo-claude", "Claude", "claude", 0.31, "Current session",
                         "https://claude.ai/settings/usage"),
            DemoProvider("demo-codex", "Codex", "openai", 0.22, "5h limit",
                         "https://chatgpt.com/#settings/Account"),
            DemoProvider("demo-grok", "Grok", "grok", 0.0, "Requests today · no limit published",
                         "https://grok.com/?_s=usage"),
        ]
    store = UsageStore(providers, refresh_interval=int(config.get("refreshInterval", 60)))
    overlay = NotchOverlay(store, config)
    overlay.show()
    store.start()
    # First seconds unfolded so the notch is findable on the Plasma edge.
    if not config.get("alwaysOpen"):
        overlay._expand()
        QTimer.singleShot(4000, overlay._maybe_fold)

    tray = QSystemTrayIcon(app)
    from PyQt5.QtGui import QPixmap, QIcon, QColor, QPainter
    icon_pix = QPixmap(32, 32)
    icon_pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(icon_pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#000000"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 2, 24, 28, 8, 8)
    painter.end()
    tray.setIcon(QIcon(icon_pix))
    tray.setToolTip("Codenotch")
    menu = QMenu()
    quit_act = QAction("Sair do Codenotch", menu)
    quit_act.triggered.connect(app.quit)
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.show()

    app.aboutToQuit.connect(lambda: (save_config(overlay._config), store.shutdown()))
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
