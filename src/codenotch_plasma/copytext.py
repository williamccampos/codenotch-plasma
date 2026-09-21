"""Relative reset and elapsed copy (copy.js), localized for Brazil."""

from datetime import datetime, timezone

_MONTHS_PT = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)
_WEEKDAYS_PT = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _aware_now(now=None):
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is None:
        return now.astimezone()
    return now.astimezone()


def _aware_at(value, ref=None):
    if value is None:
        return None
    if value.tzinfo is None:
        ref = ref or _aware_now()
        return value.replace(tzinfo=ref.tzinfo)
    return value.astimezone()


def _pair(resets_at, now=None):
    now = _aware_now(now)
    resets_at = _aware_at(resets_at, now)
    return now, resets_at


def reset_text(resets_at, now=None):
    if resets_at is None:
        return ""
    now, resets_at = _pair(resets_at, now)
    seconds = (resets_at - now).total_seconds()
    if seconds <= 0:
        return "Resetting…"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"Resets in {max(1, minutes)} min"
    days = (resets_at.date() - now.date()).days
    if days >= 7:
        return f"Resets {resets_at.day} de {_MONTHS_PT[resets_at.month - 1]}"
    return f"Resets {resets_at.strftime('%a %-I:%M %p').replace(' 0', ' ')}"


def reset_short(resets_at, now=None):
    """Codex-style reset label: 19:33 today, otherwise 26 de set."""
    if resets_at is None:
        return ""
    now, local = _pair(resets_at, now)
    if local.date() == now.date():
        return local.strftime("%H:%M")
    return f"{local.day} de {_MONTHS_PT[local.month - 1]}"


def elapsed_text(since, now=None):
    now = _aware_now(now)
    since = _aware_at(since, now)
    seconds = max(0, (now - since).total_seconds())
    if seconds < 45:
        return "just now"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{max(1, minutes)} min"
    hours = minutes // 60
    rest = minutes % 60
    return f"{hours} hr" if rest == 0 else f"{hours} hr {rest} min"


def percent_text(fraction):
    return f"{round(fraction * 100)}%"


def remaining_text(used_fraction):
    return f"{round((1 - used_fraction) * 100)}%"


def remaining_percent_text(remaining_fraction):
    return f"{round(remaining_fraction * 100)}%"


def count_text(used, approximate):
    noun = "request" if used == 1 else "requests"
    return f"{'~' if approximate else ''}{used} {noun} today"
