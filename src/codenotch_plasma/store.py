"""Usage store: one reading per provider, shared by the overlay."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .archive import load_archive, save_archive
from .copytext import percent_text
from .httputil import ProviderError
from .layout import band
from .sessions import antigravity_sessions, read_claude_sessions, summarize


IDLE_REFRESH = 5 * 60 * 1000
STALE_AFTER = 15 * 60 * 1000
RESET_LEAD_MS = 60 * 1000
RESET_AFTER_MS = 30 * 1000
RESET_WATCH_MS = 15 * 1000


class UsageStore(QObject):
    changed = pyqtSignal(str)
    _fetch_done = pyqtSignal(object, object, object)

    def __init__(self, providers, refresh_interval=60, parent=None):
        super().__init__(parent)
        self.providers = providers
        self._refresh_interval = max(15, refresh_interval)
        self._states = {
            p.id: {"snapshot": None, "status": "error", "error": None, "fetching": False, "attemptedAt": 0}
            for p in providers
        }
        self._archive = {}
        self._sessions = {}
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="codenotch")
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._refresh_all("tick"))
        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._scan_sessions)
        self._reset_timer = QTimer(self)
        self._reset_timer.timeout.connect(self._check_reset_refreshes)
        self._fetch_done.connect(self._apply)

    def start(self):
        self._restore_archive()
        self._scan_sessions()
        self._refresh_all("initial")
        self._timer.start(self._refresh_interval * 1000)
        self._session_timer.start(5000)
        self._reset_timer.start(RESET_WATCH_MS)
        self._schedule_reset_refreshes()

    def shutdown(self):
        self._timer.stop()
        self._session_timer.stop()
        self._reset_timer.stop()
        self._pool.shutdown(wait=False)

    def reload_providers(self, providers):
        self.providers = providers
        next_states = {}
        for provider in providers:
            state = self._states.get(provider.id)
            if state:
                next_states[provider.id] = state
            else:
                next_states[provider.id] = {
                    "snapshot": None,
                    "status": "error",
                    "error": None,
                    "fetching": False,
                    "attemptedAt": 0,
                }
                entry = self._archive.get(provider.id)
                if entry and entry.get("snapshot"):
                    snapshot = entry["snapshot"]
                    if provider.id == "codex":
                        snapshot = _patch_codex_snapshot(snapshot)
                    elif provider.id == "cursor-personal":
                        snapshot = _patch_cursor_personal_snapshot(snapshot)
                    next_states[provider.id]["snapshot"] = snapshot
                    next_states[provider.id]["attemptedAt"] = snapshot.get("fetchedAt") or 0
                    self.state_of(provider.id)
        self._states = next_states
        self._refresh_all("initial")
        self._schedule_reset_refreshes()
        for provider in providers:
            self.changed.emit(provider.id)

    def state_of(self, provider_id, now=None):
        now = now or _now_ms()
        state = self._states.get(provider_id)
        if not state:
            return None
        if not state["snapshot"]:
            state["status"] = "error"
        else:
            state["status"] = "ok" if now - state["snapshot"]["fetchedAt"] < STALE_AFTER else "stale"
        return state

    def activity(self, provider_id):
        return summarize(self._sessions.get(provider_id))

    def _restore_archive(self):
        self._archive = load_archive()
        legacy = self._archive.pop("cursor", None)
        if legacy and "cursor-personal" not in self._archive:
            self._archive["cursor-personal"] = legacy
        for provider in self.providers:
            entry = self._archive.get(provider.id)
            if not entry:
                continue
            state = self._states[provider.id]
            snapshot = entry.get("snapshot")
            if provider.id == "codex":
                snapshot = _patch_codex_snapshot(snapshot)
            elif provider.id == "cursor-personal":
                snapshot = _patch_cursor_personal_snapshot(snapshot)
            state["snapshot"] = snapshot
            state["attemptedAt"] = (entry.get("snapshot") or {}).get("fetchedAt") or 0
            if entry.get("backoffUntil"):
                provider.backoff_until = entry["backoffUntil"]
            self.state_of(provider.id)

    def _busy(self, provider_id):
        state = (self.activity(provider_id) or {}).get("state")
        return state in ("working", "waiting")

    def _refresh_all(self, reason):
        now = _now_ms()
        for provider in self.providers:
            state = self._states[provider.id]
            before = state["status"]
            due = now - state["attemptedAt"] >= IDLE_REFRESH
            if (
                due
                or (reason == "tick" and self._busy(provider.id))
                or self._needs_reset_refresh(provider.id, now)
            ):
                self._refresh(provider)
            elif self.state_of(provider.id, now)["status"] != before:
                self.changed.emit(provider.id)

    def refresh(self, provider_id):
        provider = next((p for p in self.providers if p.id == provider_id), None)
        if provider:
            self._refresh(provider)

    def _refresh(self, provider):
        state = self._states[provider.id]
        if state["fetching"]:
            return
        state["fetching"] = True
        state["attemptedAt"] = _now_ms()
        self._pool.submit(self._fetch_job, provider)

    def _fetch_job(self, provider):
        error = None
        snapshot = None
        try:
            snapshot = provider.fetch(self._states[provider.id]["snapshot"])
            snapshot = {**snapshot, "fetchedAt": _now_ms()}
        except ProviderError as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001
            error = ProviderError("network", str(exc) or "Couldn't read usage")
        self._fetch_done.emit(provider, snapshot, error)

    def _apply(self, provider, snapshot, error):
        state = self._states[provider.id]
        state["fetching"] = False
        read = snapshot is not None
        if read:
            if provider.id == "codex":
                snapshot = _patch_codex_snapshot(snapshot)
            elif provider.id == "cursor-personal":
                snapshot = _patch_cursor_personal_snapshot(snapshot)
            state["snapshot"] = snapshot
            state["error"] = None
        else:
            state["error"] = error
        self._remember(provider, read)
        self.changed.emit(provider.id)
        if read:
            self._schedule_reset_refreshes()

    def _check_reset_refreshes(self):
        now = _now_ms()
        for provider in self.providers:
            if self._needs_reset_refresh(provider.id, now):
                self._refresh(provider)

    def _needs_reset_refresh(self, provider_id, now):
        state = self._states.get(provider_id)
        if not state or state.get("fetching"):
            return False
        snapshot = state.get("snapshot")
        if not snapshot:
            return False
        fetched = snapshot.get("fetchedAt", 0)
        for reset_ms in _window_reset_times_ms(snapshot):
            if now >= reset_ms - RESET_LEAD_MS and fetched < reset_ms:
                return True
        return False

    def _schedule_reset_refreshes(self):
        now = _now_ms()
        week_ms = 7 * 24 * 60 * 60 * 1000
        for provider in self.providers:
            snapshot = self._states[provider.id].get("snapshot")
            if not snapshot:
                continue
            for reset_ms in _window_reset_times_ms(snapshot):
                delay = reset_ms - now + RESET_AFTER_MS
                if 0 < delay <= week_ms:
                    QTimer.singleShot(
                        delay,
                        lambda pid=provider.id: self.refresh(pid),
                    )

    def _remember(self, provider, read):
        entry = self._archive.setdefault(provider.id, {"snapshot": None, "backoffUntil": None})
        state = self._states[provider.id]
        changed = read
        if read:
            entry["snapshot"] = state["snapshot"]
        backoff = getattr(provider, "backoff_until", None)
        if entry.get("backoffUntil") != backoff:
            entry["backoffUntil"] = backoff
            changed = True
        if changed:
            try:
                save_archive(self._archive)
            except OSError:
                pass

    def _scan_sessions(self):
        for provider in self.providers:
            if not getattr(provider, "tracks_sessions", False):
                continue
            if provider.id == "claude":
                found = read_claude_sessions(provider.sessions_dir())
            elif provider.id == "antigravity":
                found = antigravity_sessions(provider.brains_dirs())
            else:
                found = self._sessions.get(provider.id) or []
            if found != self._sessions.get(provider.id):
                self._sessions[provider.id] = found
                self.changed.emit(provider.id)


def glyph_dimmed(fraction):
    """Dim the provider glyph only when its principal quota is exhausted."""
    if not isinstance(fraction, (int, float)):
        return False
    return band(fraction) == "exhausted"


def _reset_at_ms(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str):
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return None
    if hasattr(value, "timestamp"):
        return int(value.timestamp() * 1000)
    return None


def _window_reset_times_ms(snapshot):
    times = []
    for window in snapshot.get("windows") or []:
        reset_ms = _reset_at_ms(window.get("resetsAt"))
        if reset_ms is not None:
            times.append(reset_ms)
    return times


def dual_ring_windows(snapshot):
    """Outer = short window (5h), inner = longer window (weekly)."""
    if not snapshot:
        return None
    by_id = {w.get("id"): w for w in snapshot.get("windows") or []}
    primary = by_id.get("primary")
    secondary = by_id.get("secondary")
    if not primary or not secondary:
        return None
    outer = primary.get("usedFraction")
    inner = secondary.get("usedFraction")
    if not isinstance(outer, (int, float)) or not isinstance(inner, (int, float)):
        return None
    return {"outer": outer, "inner": inner}


def _patch_cursor_personal_snapshot(snapshot):
    if not snapshot:
        return snapshot
    windows = snapshot.get("windows") or []
    if any(w.get("id") == "plan" for w in windows):
        return {**snapshot, "headlineID": "plan"}
    return snapshot


def _patch_codex_snapshot(snapshot):
    if not snapshot:
        return snapshot
    windows = snapshot.get("windows") or []
    if any(w.get("id") == "secondary" for w in windows):
        return {**snapshot, "headlineID": "secondary", "ringMode": "dual"}
    return snapshot


def headline_of(snapshot):
    if not snapshot or not snapshot.get("windows"):
        return None
    hid = snapshot.get("headlineID")
    return next((w for w in snapshot["windows"] if w.get("id") == hid), snapshot["windows"][0])


def headline_text(snapshot):
    headline = headline_of(snapshot)
    if isinstance((headline or {}).get("usedFraction"), (int, float)):
        return percent_text(headline["usedFraction"])
    if isinstance((headline or {}).get("used"), (int, float)):
        return str(int(headline["used"]))
    return "—"


def _now_ms():
    return int(time.time() * 1000)
