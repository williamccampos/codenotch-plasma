"""Usage store: one reading per provider, shared by the overlay."""

import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .archive import load_archive, save_archive
from .copytext import percent_text
from .httputil import ProviderError
from .layout import band
from .sessions import antigravity_sessions, grok_requests_today, read_claude_sessions, summarize


DEFAULT_IDLE_REFRESH = 5 * 60
STALE_AFTER = 15 * 60 * 1000
ACTIVITY_DEBOUNCE_MS = 2_000
ACTIVITY_RETRIES_MS = (10_000, 30_000)
MIN_REFRESH_GAP_MS = 2_000
RESET_LEAD_MS = 60 * 1000
RESET_AFTER_MS = 30 * 1000
RESET_WATCH_MS = 15 * 1000


class UsageStore(QObject):
    changed = pyqtSignal(str)
    _fetch_done = pyqtSignal(object, object, object, object)
    _activity_done = pyqtSignal(str, object)

    def __init__(self, providers, refresh_interval=60, idle_refresh_interval=DEFAULT_IDLE_REFRESH, parent=None):
        super().__init__(parent)
        self.providers = providers
        self._refresh_interval = max(15, refresh_interval)
        self._idle_refresh_interval = max(self._refresh_interval, idle_refresh_interval)
        self._generations = {p.id: 0 for p in providers}
        self._states = {
            p.id: self._new_state()
            for p in providers
        }
        self._archive = {}
        self._sessions = {}
        self._activity_signatures = {}
        self._activity_counts = {}
        self._activity_fingerprints = {}
        self._antigravity_fingerprints = {}
        self._antigravity_cache = {}
        self._activity_seen_at = {}
        self._activity_scanning = set()
        self._activity_timers = {}
        self._retry_timers = {}
        self._reset_timers = {}
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="codenotch")
        self._activity_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="codenotch-activity")
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._refresh_all("tick"))
        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._scan_sessions)
        self._reset_timer = QTimer(self)
        self._reset_timer.timeout.connect(self._check_reset_refreshes)
        self._fetch_done.connect(self._apply)
        self._activity_done.connect(self._apply_activity)

    def start(self):
        self._restore_archive()
        self._scan_sessions()
        self._refresh_all("initial")
        self._timer.start(self._refresh_interval * 1000)
        self._session_timer.start(1000)
        self._reset_timer.start(RESET_WATCH_MS)
        self._schedule_reset_refreshes()

    def shutdown(self):
        self._timer.stop()
        self._session_timer.stop()
        self._reset_timer.stop()
        for timer in (*self._activity_timers.values(), *self._retry_timers.values(), *self._reset_timers.values()):
            timer.stop()
        self._pool.shutdown(wait=False)
        self._activity_pool.shutdown(wait=False)

    def reload_providers(self, providers):
        previous_ids = set(self._states)
        for provider_id in list(self._activity_timers):
            self._stop_timer(self._activity_timers, provider_id)
        for provider_id in list(self._retry_timers):
            self._stop_timer(self._retry_timers, provider_id)
        for provider_id in list(self._generations):
            self._generations[provider_id] += 1
        for provider in providers:
            self._generations.setdefault(provider.id, 0)
        self.providers = providers
        next_states = {}
        for provider in providers:
            state = self._states.get(provider.id)
            if state:
                state = dict(state)
                state["generation"] = self._generations[provider.id]
                state["fetching"] = False
                state["nextRefreshAt"] = None
                state["activityRetries"] = 0
                next_states[provider.id] = state
            else:
                next_states[provider.id] = self._new_state()
                next_states[provider.id]["generation"] = self._generations[provider.id]
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
        for provider in providers:
            if provider.id not in previous_ids:
                self._refresh(provider)
        self._schedule_reset_refreshes()
        for provider in providers:
            self.changed.emit(provider.id)

    def state_of(self, provider_id, now=None):
        now = now or _now_ms()
        state = self._states.get(provider_id)
        if not state:
            return None
        if state["snapshot"]:
            age = now - state["snapshot"].get("fetchedAt", 0)
            if age >= STALE_AFTER:
                state["status"] = "stale"
            elif state.get("error"):
                state["status"] = _error_status(state["error"])
            else:
                state["status"] = "ok"
        elif state.get("fetching"):
            state["status"] = "refreshing"
        elif state.get("error"):
            state["status"] = _error_status(state["error"])
        else:
            state["status"] = "unavailable"
        return state

    @staticmethod
    def _new_state():
        return {
            "snapshot": None,
            "status": "unavailable",
            "error": None,
            "fetching": False,
            "attemptedAt": 0,
            "lastSuccessAt": 0,
            "nextRefreshAt": None,
            "generation": 0,
            "activityRetries": 0,
            "failureCount": 0,
        }

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
            state["lastSuccessAt"] = state["attemptedAt"]
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
            interval = self._refresh_interval * 1000 if self._busy(provider.id) else self._idle_refresh_interval * 1000
            due = now - state["attemptedAt"] >= interval
            if (
                reason == "initial"
                or due
                or self._needs_reset_refresh(provider.id, now)
            ):
                self._refresh(provider)
            else:
                self.state_of(provider.id, now)

    def refresh(self, provider_id):
        provider = next((p for p in self.providers if p.id == provider_id), None)
        if provider:
            self._refresh(provider)

    def _refresh(self, provider):
        state = self._states[provider.id]
        if state["fetching"]:
            return
        now = _now_ms()
        provider_backoff = getattr(provider, "backoff_until", None)
        next_allowed = provider_backoff or 0
        if state.get("error"):
            next_allowed = max(next_allowed, state.get("nextRefreshAt") or 0)
        if now < next_allowed or now - state["attemptedAt"] < MIN_REFRESH_GAP_MS:
            return
        previous = state.get("snapshot")
        generation = state["generation"]
        state["fetching"] = True
        state["attemptedAt"] = now
        state["nextRefreshAt"] = now + self._refresh_interval * 1000
        self.changed.emit(provider.id)
        self._pool.submit(self._fetch_job, provider, previous, generation)

    def _fetch_job(self, provider, previous, generation):
        error = None
        snapshot = None
        try:
            snapshot = provider.fetch(previous)
            snapshot = {**snapshot, "fetchedAt": _now_ms()}
        except ProviderError as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001
            error = ProviderError("network", str(exc) or "Couldn't read usage")
        self._fetch_done.emit(provider, snapshot, error, generation)

    def _apply(self, provider, snapshot, error, generation):
        state = self._states.get(provider.id)
        if not state or state["generation"] != generation:
            return
        previous = state.get("snapshot")
        state["fetching"] = False
        read = snapshot is not None
        if read:
            if provider.id == "codex":
                snapshot = _patch_codex_snapshot(snapshot)
            elif provider.id == "cursor-personal":
                snapshot = _patch_cursor_personal_snapshot(snapshot)
            state["snapshot"] = snapshot
            state["error"] = None
            state["lastSuccessAt"] = snapshot["fetchedAt"]
            state["failureCount"] = 0
            state["nextRefreshAt"] = snapshot["fetchedAt"] + self._refresh_interval * 1000
            state["previousSnapshot"] = previous if previous and not _same_usage(previous, snapshot) else None
            self._stop_timer(self._retry_timers, provider.id)
            if not _same_usage(previous, snapshot):
                state["activityRetries"] = 0
            elif self._busy(provider.id):
                self._schedule_activity_retry(provider.id)
        else:
            state["error"] = error
            state["failureCount"] += 1
            retry_at = getattr(provider, "backoff_until", None)
            if not retry_at:
                base_delay = min(15 * 60_000, 15_000 * (2 ** min(6, state["failureCount"] - 1)))
                retry_at = _now_ms() + int(base_delay * random.uniform(0.8, 1.2))
            state["nextRefreshAt"] = retry_at
            self._schedule_error_retry(provider.id, retry_at)
        self._remember(provider, read)
        self.state_of(provider.id)
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
        if _now_ms() < (state.get("nextRefreshAt") or 0):
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
        wanted = {}
        for provider in self.providers:
            snapshot = self._states[provider.id].get("snapshot")
            if not snapshot:
                continue
            for reset_ms in _window_reset_times_ms(snapshot):
                delay = reset_ms - now + RESET_AFTER_MS
                if 0 < delay <= week_ms:
                    key = (provider.id, reset_ms)
                    wanted[key] = delay
        for key in list(self._reset_timers):
            if key not in wanted:
                self._stop_timer(self._reset_timers, key)
        for key, delay in wanted.items():
            timer = self._reset_timers.get(key)
            if timer and timer.isActive():
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda k=key: self._fire_reset(k))
            self._reset_timers[key] = timer
            timer.start(max(1, delay))

    def _fire_reset(self, key):
        timer = self._reset_timers.pop(key, None)
        if timer:
            timer.deleteLater()
        provider_id, _reset_ms = key
        self.refresh(provider_id)

    @staticmethod
    def _stop_timer(timers, key):
        timer = timers.pop(key, None)
        if timer:
            timer.stop()
            timer.deleteLater()

    def _schedule_activity_refresh(self, provider_id):
        timer = self._activity_timers.get(provider_id)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda pid=provider_id: self.refresh(pid))
            self._activity_timers[provider_id] = timer
        timer.start(ACTIVITY_DEBOUNCE_MS)

    def _schedule_activity_retry(self, provider_id):
        state = self._states.get(provider_id)
        if not state or state.get("fetching"):
            return
        retries = state.get("activityRetries", 0)
        if retries >= len(ACTIVITY_RETRIES_MS):
            return
        self._stop_timer(self._retry_timers, provider_id)
        delay = ACTIVITY_RETRIES_MS[retries]
        state["activityRetries"] = retries + 1
        state["nextRefreshAt"] = _now_ms() + delay
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda pid=provider_id: self.refresh(pid))
        self._retry_timers[provider_id] = timer
        timer.start(delay)

    def _schedule_error_retry(self, provider_id, retry_at):
        self._stop_timer(self._retry_timers, provider_id)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda pid=provider_id: self._retry_after_timeout(pid))
        self._retry_timers[provider_id] = timer
        delay = max(250, retry_at - _now_ms() + 250)
        timer.start(min(delay, 24 * 60 * 60 * 1000))

    def _retry_after_timeout(self, provider_id):
        state = self._states.get(provider_id)
        provider = next((p for p in self.providers if p.id == provider_id), None)
        if not state or not provider:
            return
        backoff = getattr(provider, "backoff_until", None) or 0
        retry_at = max(state.get("nextRefreshAt") or 0, backoff)
        if _now_ms() < retry_at:
            self._schedule_error_retry(provider_id, retry_at)
            return
        self._retry_timers.pop(provider_id, None)
        self._refresh(provider)

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
            if provider.id in self._activity_scanning:
                continue
            self._activity_scanning.add(provider.id)
            self._activity_pool.submit(self._scan_provider_activity, provider)

    def _scan_provider_activity(self, provider):
        try:
            if provider.id == "claude":
                found = read_claude_sessions(provider.sessions_dir())
            elif provider.id == "antigravity":
                found = self._antigravity_activity(provider)
            elif provider.id == "grok":
                found = self._grok_activity(provider)
            else:
                found = []
        except Exception:  # noqa: BLE001
            found = None
        self._activity_done.emit(provider.id, found)

    def _apply_activity(self, provider_id, found):
        self._activity_scanning.discard(provider_id)
        if provider_id not in self._states or found is None:
            return
        if found != self._sessions.get(provider_id):
            previous_sessions = self._sessions.get(provider_id) or []
            old_signature = self._activity_signatures.get(provider_id)
            signature = _session_signature(found)
            self._sessions[provider_id] = found
            self._activity_signatures[provider_id] = signature
            self.changed.emit(provider_id)
            was_active = any(s.get("state") in ("busy", "working", "waiting") for s in previous_sessions)
            is_active = any(s.get("state") in ("busy", "working", "waiting") for s in found)
            if signature != old_signature and (was_active or is_active):
                self._states[provider_id]["activityRetries"] = 0
                self._schedule_activity_refresh(provider_id)

    def _antigravity_activity(self, provider):
        fingerprint = []
        for root in provider.brains_dirs():
            base = Path(root)
            if not base.is_dir():
                continue
            for child in base.iterdir():
                path = child / ".system_generated" / "logs" / "transcript.jsonl"
                try:
                    stat = path.stat()
                except OSError:
                    continue
                fingerprint.append((str(path), stat.st_ino, stat.st_size, stat.st_mtime_ns))
        fingerprint = tuple(sorted(fingerprint))
        if self._antigravity_fingerprints.get(provider.id) != fingerprint:
            self._antigravity_fingerprints[provider.id] = fingerprint
            sessions = antigravity_sessions(provider.brains_dirs())
            self._antigravity_cache[provider.id] = sessions
            return sessions
        sessions = self._antigravity_cache.get(provider.id) or []
        if not sessions:
            return []
        now = _now_ms()
        sessions = [s for s in sessions if now - (s.get("since") or 0) < 45_000]
        self._antigravity_cache[provider.id] = sessions
        return sessions

    def _grok_activity(self, provider):
        root = Path(provider.sessions_dir())
        fingerprint = []
        if root.is_dir():
            for path in root.glob("*/*/updates.jsonl"):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                fingerprint.append((str(path), stat.st_ino, stat.st_size, stat.st_mtime_ns))
        fingerprint = tuple(sorted(fingerprint))
        if self._activity_fingerprints.get(provider.id) == fingerprint:
            count = self._activity_counts.get(provider.id, 0)
        else:
            self._activity_fingerprints[provider.id] = fingerprint
            count = grok_requests_today(provider.sessions_dir())
        previous = self._activity_counts.get(provider.id)
        self._activity_counts[provider.id] = count
        now = _now_ms()
        if previous is not None and count > previous:
            self._activity_seen_at[provider.id] = now
        seen_at = self._activity_seen_at.get(provider.id)
        if seen_at is None or now - seen_at >= 45_000:
            return []
        return [{
            "id": "grok.recent-request",
            "name": "Grok CLI",
            "detail": "Recent request detected",
            "state": "busy",
            "since": seen_at,
        }]


def glyph_dimmed(fraction):
    """Dim the provider glyph only when its principal quota is exhausted."""
    if not isinstance(fraction, (int, float)):
        return False
    return band(fraction) == "exhausted"


def _error_status(error):
    kind = getattr(error, "kind", "")
    if kind == "rateLimited":
        return "rate_limited"
    if kind in ("needsAuth", "expired"):
        return "auth_required"
    if kind in ("offline", "network"):
        return "offline"
    return "error"


def _session_signature(sessions):
    return tuple(sorted(
        (s.get("id"), s.get("state"), s.get("waitingFor"), s.get("name"))
        for s in sessions
    ))


def _same_usage(previous, current):
    if not previous or not current:
        return False
    old = {key: value for key, value in previous.items() if key != "fetchedAt"}
    new = {key: value for key, value in current.items() if key != "fetchedAt"}
    return old == new


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
