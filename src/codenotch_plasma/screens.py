"""Screen selection helpers for multi-monitor setups."""

from PyQt5.QtWidgets import QApplication

PRIMARY_SCREEN = "primary"


def normalize_screen_choice(choice):
    if not choice or choice == PRIMARY_SCREEN:
        return PRIMARY_SCREEN
    return str(choice)


def screen_label(screen):
    geo = screen.geometry()
    name = screen.name() or "Monitor"
    primary = QApplication.primaryScreen()
    suffix = " · principal" if primary and screen == primary else ""
    return f"{name} ({geo.width()}×{geo.height()}){suffix}"


def primary_screen_label():
    screen = QApplication.primaryScreen() if QApplication.instance() else None
    if screen is None:
        return "Tela principal"
    return f"Tela principal — {screen_label(screen)}"


def list_screen_choices():
    app = QApplication.instance()
    if app is None:
        return []
    entries = []
    for screen in app.screens():
        entries.append({
            "id": screen.name(),
            "label": screen_label(screen),
            "screen": screen,
            "is_primary": screen == app.primaryScreen(),
        })
    return entries


def resolve_screen(choice):
    app = QApplication.instance()
    if app is None:
        return None
    choice = normalize_screen_choice(choice)
    if choice == PRIMARY_SCREEN:
        return app.primaryScreen()
    for screen in app.screens():
        if screen.name() == choice:
            return screen
    return app.primaryScreen()


def choice_is_active(choice, screen_id):
    return normalize_screen_choice(choice) == normalize_screen_choice(screen_id)
