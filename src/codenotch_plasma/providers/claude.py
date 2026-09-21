import json
from datetime import datetime, timezone

from ..httputil import ProviderError, exists, home, read_json, request


ENDPOINT = "https://api.anthropic.com/api/oauth/usage"


class ClaudeProvider:
    id = "claude"
    display_name = "Claude"
    glyph = "claude"
    manage_url = "https://claude.ai/settings/usage"
    tracks_sessions = True

    def __init__(self, config_dir=None):
        self._config_dir = config_dir or home(".claude")
        self._credentials_path = os_path(self._config_dir, ".credentials.json")
        self.backoff_until = None

    def available(self):
        return exists(self._credentials_path)

    def account(self):
        oauth = (read_json(self._credentials_path) or {}).get("claudeAiOauth") or {}
        return {"plan": oauth.get("subscriptionType"), "source": "Claude Code"}

    def sessions_dir(self):
        return os_path(self._config_dir, "sessions")

    def _token(self):
        oauth = (read_json(self._credentials_path) or {}).get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        if not token:
            raise ProviderError("needsAuth", "Sign in to Claude Code to read your usage")
        expires = oauth.get("expiresAt")
        if expires and expires < _now_ms():
            raise ProviderError(
                "expired",
                "Claude Code's sign-in has expired — run `claude` once to refresh it",
            )
        return token

    def fetch(self, _previous=None):
        if self.backoff_until and self.backoff_until > _now_ms():
            raise ProviderError("rateLimited", "Claude asked us to wait before reading again")
        token = self._token()
        status, text, headers = request("GET", ENDPOINT, {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
        if status in (401, 403):
            raise ProviderError("needsAuth", "Sign in to Claude Code to read your usage")
        if status == 429:
            retry = _retry_after(headers)
            self.backoff_until = _now_ms() + max(60, retry) * 1000
            raise ProviderError("rateLimited", "Claude asked us to wait before reading again")
        if status < 200 or status >= 300:
            raise ProviderError("badResponse", f"Claude answered HTTP {status}")
        self.backoff_until = None
        json_body = json.loads(text)
        return {"windows": windows_from(json_body), "headlineID": "session"}


def windows_from(body):
    windows = []
    for limit in body.get("limits") or []:
        resets_at = _parse_date(limit.get("resets_at"))
        if not resets_at or not isinstance(limit.get("percent"), (int, float)):
            continue
        windows.append({
            "id": limit.get("kind"),
            "label": _label_for_kind(limit.get("kind"), limit.get("scope")),
            "usedFraction": limit["percent"] / 100,
            "resetsAt": resets_at,
        })

    def merge(window, wid, label):
        if not window:
            return
        resets_at = _parse_date(window.get("resets_at"))
        if not resets_at or any(w["id"] == wid for w in windows):
            return
        windows.append({
            "id": wid,
            "label": label,
            "usedFraction": (window.get("utilization") or 0) / 100,
            "resetsAt": resets_at,
        })

    merge(body.get("five_hour"), "session", "Current session")
    merge(body.get("seven_day"), "weekly_all", "All models")
    rank = {"session": 0, "weekly_all": 1}
    windows.sort(key=lambda w: (rank.get(w["id"], 2), w["id"] or ""))
    return windows


def _label_for_kind(kind, scope):
    model = (scope or {}).get("model", {})
    if isinstance(model, dict) and model.get("display_name"):
        return model["display_name"]
    if kind == "session":
        return "Current session"
    if kind == "weekly_all":
        return "All models"
    if kind == "weekly_opus":
        return "Opus"
    if kind == "weekly_sonnet":
        return "Sonnet"
    return (kind or "").replace("weekly_", "").replace("_", " ").title()


def os_path(*parts):
    return "/".join(str(p).rstrip("/") for p in parts)


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _parse_date(text):
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _retry_after(headers):
    try:
        return int(float(headers.get("Retry-After") or headers.get("retry-after") or 0))
    except ValueError:
        return 0
