"""Theme mode resolution for notch and system icons."""

THEME_MODES = ("auto", "dark", "light")
_CYCLE = ("auto", "dark", "light")


def normalize_mode(mode):
    return mode if mode in THEME_MODES else "auto"


def resolve_dark(mode, system_dark=True):
    mode = normalize_mode(mode)
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return bool(system_dark)


def next_mode(mode):
    mode = normalize_mode(mode)
    index = _CYCLE.index(mode)
    return _CYCLE[(index + 1) % len(_CYCLE)]


def toggle_fixed_mode(resolved_dark):
    """Switch between explicit dark and light (skips auto)."""
    return "light" if resolved_dark else "dark"


def mode_label(mode):
    labels = {
        "auto": "Automático",
        "dark": "Escuro",
        "light": "Claro",
    }
    return labels.get(normalize_mode(mode), "Automático")
