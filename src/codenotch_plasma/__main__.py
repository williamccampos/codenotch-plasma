import json
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from .glyphs import clear_adapted_cache
from .icons import (
    install_theme_listener,
    is_dark_theme,
    load_app_icon,
    set_theme_mode,
    sync_system_icons,
)
from .layout import apply_system_theme, configure_layout, set_appearance
from .overlay import NotchOverlay
from .provider_order import joining_connected, remember
from .providers import discover_providers, tool_catalog
from .store import UsageStore
from .theme import mode_label, normalize_mode, resolve_dark


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
        "themeMode": "auto",
        "disabledProviders": [],
        "providerOrder": [],
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


def demo_providers():
    return [
        DemoProvider("demo-claude", "Claude", "claude", 0.31, "Current session",
                     "https://claude.ai/settings/usage"),
        DemoProvider("demo-codex", "Codex", "openai", 0.22, "5h limit",
                     "https://chatgpt.com/#settings/Account"),
        DemoProvider("demo-grok", "Grok", "grok", 0.0, "Requests today · no limit published",
                     "https://grok.com/?_s=usage"),
    ]


def active_providers(config):
    providers = discover_providers(
        disabled=config.get("disabledProviders"),
        order=config.get("providerOrder"),
    )
    if providers:
        return providers
    if not any(tool["installed"] for tool in tool_catalog()):
        return demo_providers()
    return []


class CodenotchApp:
    def __init__(self, app):
        self._app = app
        self._config = load_config()
        apply_config(self._config)
        self._store = UsageStore(
            active_providers(self._config),
            refresh_interval=int(self._config.get("refreshInterval", 60)),
        )
        self._tray = None
        self._overlay = NotchOverlay(
            self._store,
            self._config,
            on_theme_change=self._on_theme_mode_changed,
            open_menu=self._popup_menu,
        )
        self._overlay.show()
        self._store.start()
        if not self._config.get("alwaysOpen"):
            self._overlay._expand()
            QTimer.singleShot(4000, self._overlay._maybe_fold)
        self._icon_sync_timer = QTimer()
        self._icon_sync_timer.setSingleShot(True)
        self._icon_sync_timer.setInterval(300)
        self._icon_sync_timer.timeout.connect(self._apply_system_icons)
        install_theme_listener(lambda *_args: self._icon_sync_timer.start())
        self._apply_system_icons()
        self._tray = self._build_tray()
        self._tray.show()
        self._app.aboutToQuit.connect(self._shutdown)

    def _shutdown(self):
        save_config(self._overlay._config)
        self._store.shutdown()

    def _provider_enabled(self, provider_id):
        return provider_id not in set(self._config.get("disabledProviders") or [])

    def _connected_ids(self, disabled):
        ids = set()
        for tool in tool_catalog():
            if tool["id"] not in disabled and tool["installed"]:
                ids.add(tool["id"])
        return ids

    def _set_provider_enabled(self, provider_id, enabled):
        disabled = list(self._config.get("disabledProviders") or [])
        has = provider_id in disabled
        if enabled and has:
            disabled.remove(provider_id)
        elif not enabled and not has:
            disabled.append(provider_id)
        self._config["disabledProviders"] = disabled

        order = list(self._config.get("providerOrder") or [])
        if not order:
            order = [p.id for p in self._store.providers]
        if enabled:
            order = joining_connected(provider_id, order, self._connected_ids(disabled))
        providers = discover_providers(disabled=disabled, order=order)
        self._config["providerOrder"] = remember([p.id for p in providers], order)
        save_config(self._config)
        self._store.reload_providers(providers)
        self._overlay.reload_providers()

    def _resolved_dark(self):
        mode = normalize_mode(self._config.get("themeMode", "auto"))
        return resolve_dark(mode, is_dark_theme())

    def _apply_system_icons(self):
        mode = normalize_mode(self._config.get("themeMode", "auto"))
        dark = resolve_dark(mode, is_dark_theme())
        set_theme_mode(mode)
        sync_system_icons(force=True)
        apply_system_theme(
            dark=dark,
            opacity=float(self._config.get("opacity", 1)),
        )
        clear_adapted_cache()
        self._overlay.set_theme_mode(mode)
        self._overlay.update()
        icon = load_app_icon(22, for_tray=True)
        if self._tray is not None:
            self._tray.setIcon(icon)
            self._tray.setContextMenu(self._build_menu())
        self._app.setWindowIcon(load_app_icon(32))

    def _on_theme_mode_changed(self, mode):
        self._config["themeMode"] = normalize_mode(mode)
        save_config(self._config)
        self._apply_system_icons()

    def _popup_menu(self, global_pos):
        self._build_menu(parent=self._overlay).exec_(global_pos)

    def _build_tray(self):
        tray = QSystemTrayIcon(self._app)
        tray.setIcon(load_app_icon(22, for_tray=True))
        tray.setToolTip("Codenotch")
        tray.setContextMenu(self._build_menu())
        tray.activated.connect(self._on_tray_activated)
        return tray

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Context:
            self._tray.setContextMenu(self._build_menu())

    def _build_menu(self, parent=None):
        menu = QMenu(parent)
        always = QAction("Sempre aberto", menu)
        always.setCheckable(True)
        always.setChecked(self._overlay._always_open)
        always.toggled.connect(self._overlay._set_always_open)
        menu.addAction(always)
        menu.addSeparator()
        tools = menu.addMenu("Ferramentas")
        tools.setTitle("Ferramentas")
        for tool in tool_catalog():
            subtitle = "Instalado" if tool["installed"] else "Não encontrado nesta máquina"
            action = QAction(f"{tool['title']} — {subtitle}", tools)
            action.setCheckable(True)
            action.blockSignals(True)
            action.setChecked(self._provider_enabled(tool["id"]))
            action.blockSignals(False)
            pid = tool["id"]
            action.toggled.connect(lambda checked, pid=pid: self._set_provider_enabled(pid, checked))
            tools.addAction(action)
        appearance = menu.addMenu("Aparência")
        appearance.setTitle("Aparência")
        current = normalize_mode(self._config.get("themeMode", "auto"))
        for mode in ("auto", "dark", "light"):
            action = QAction(mode_label(mode), appearance)
            action.setCheckable(True)
            action.setChecked(current == mode)
            action.triggered.connect(lambda _checked=False, mode=mode: self._on_theme_mode_changed(mode))
            appearance.addAction(action)
        quit_act = QAction("Sair do Codenotch", menu)
        quit_act.triggered.connect(self._app.quit)
        menu.addAction(quit_act)
        return menu


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName("Codenotch")
    app.setQuitOnLastWindowClosed(False)
    CodenotchApp(app)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
