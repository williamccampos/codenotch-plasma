import base64
import json
from datetime import datetime, timezone

from ..httputil import ProviderError, exists, home, read_json, request


ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"


class CodexProvider:
    id = "codex"
    display_name = "Codex"
    glyph = "openai"
    manage_url = "https://chatgpt.com/#settings/Account"
    tracks_sessions = False
    backoff_until = None

    def __init__(self, auth_path=None):
        self._auth_path = auth_path or home(".codex", "auth.json")
        self.backoff_until = None

    def available(self):
        return exists(self._auth_path)

    def account(self):
        claims = jwt_claims((read_json(self._auth_path) or {}).get("tokens", {}).get("access_token"))
        auth = (claims or {}).get("https://api.openai.com/auth") or {}
        return {"plan": auth.get("chatgpt_plan_type"), "source": "Codex"}

    def _credential(self):
        tokens = (read_json(self._auth_path) or {}).get("tokens") or {}
        access = (tokens.get("access_token") or "").strip()
        account_id = (tokens.get("account_id") or "").strip()
        if not access or not account_id:
            raise ProviderError("needsAuth", "Sign in to Codex to read your usage")
        exp = (jwt_claims(access) or {}).get("exp")
        if isinstance(exp, (int, float)) and exp * 1000 < _now_ms():
            raise ProviderError("expired", "Codex's sign-in has expired — open Codex once to refresh it")
        return access, account_id

    def fetch(self, _previous=None):
        if self.backoff_until and self.backoff_until > _now_ms():
            raise ProviderError("rateLimited", "Codex asked us to wait before reading again")
        access, account_id = self._credential()
        status, text, headers = request("GET", ENDPOINT, {
            "Authorization": f"Bearer {access}",
            "ChatGPT-Account-Id": account_id,
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
        })
        if status in (401, 403):
            raise ProviderError("needsAuth", "Sign in to Codex to read your usage")
        if status == 429:
            retry = _retry_after(headers)
            self.backoff_until = _now_ms() + max(60, retry) * 1000
            raise ProviderError("rateLimited", "Codex asked us to wait before reading again")
        if status < 200 or status >= 300:
            raise ProviderError("badResponse", f"Codex answered HTTP {status}")
        self.backoff_until = None
        body = json.loads(text)
        windows = windows_from(body)
        plan = (body.get("plan_type") or "").strip()
        has_dual = any(w.get("id") == "secondary" for w in windows)
        snapshot = {
            "windows": windows,
            "headlineID": "secondary" if has_dual else (windows[0]["id"] if windows else "primary"),
            "ringMode": "dual" if has_dual else "single",
            "fidelity": "official",
        }
        if plan:
            snapshot["note"] = plan.title()
        return snapshot


def windows_from(body, now=None):
    now_ms = now or _now_ms()
    windows = []
    rate_limit = body.get("rate_limit") or {}
    specs = (
        ("primary", rate_limit.get("primary_window")),
        ("secondary", rate_limit.get("secondary_window")),
    )
    for wid, window in specs:
        if not window:
            continue
        if not isinstance(window.get("used_percent"), (int, float)):
            raise ProviderError("badResponse", "Codex reported a window without a percentage")
        used = max(0.0, min(100.0, float(window["used_percent"]))) / 100.0
        resets_at = _reset_at(window, now_ms)
        windows.append({
            "id": wid,
            "label": _window_label(wid, window),
            "usedFraction": used,
            "resetsAt": resets_at,
        })
    if not windows:
        raise ProviderError("badResponse", "Codex reported no usage windows")
    return windows


def _window_label(wid, window):
    seconds = window.get("limit_window_seconds")
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return "Current session" if wid == "primary" else "Longer window"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m limit"
    if minutes < 60 * 24:
        return f"{int(minutes / 60)}h limit"
    days = round(minutes / (60 * 24))
    if days == 7:
        return "Weekly limit"
    if days == 30:
        return "Monthly limit"
    return f"{days}d limit"


def _reset_at(window, now_ms):
    if isinstance(window.get("reset_at"), (int, float)):
        return datetime.fromtimestamp(window["reset_at"], tz=timezone.utc)
    if isinstance(window.get("reset_after_seconds"), (int, float)):
        return datetime.fromtimestamp(now_ms / 1000 + window["reset_after_seconds"], tz=timezone.utc)
    return None


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _retry_after(headers):
    try:
        return int(float(headers.get("Retry-After") or headers.get("retry-after") or 0))
    except ValueError:
        return 0
