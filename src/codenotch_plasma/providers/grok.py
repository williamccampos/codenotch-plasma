import json
from datetime import datetime, timezone
from pathlib import Path

from ..httputil import ProviderError, exists, home, read_json, request
from ..sessions import grok_requests_today


CREDITS_ENDPOINT = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
LEDGER_ENDPOINT = "https://cli-chat-proxy.grok.com/v1/billing"
TRUSTED_ISSUER = "https://auth.x.ai"
EXPIRED_NOTE = "Sign-in expired · run grok to refresh"
NEEDS_AUTH = "Sign in to Grok (run `grok login`) to read your usage"
RATE_LIMITED = "Grok asked us to wait before reading again"


class GrokProvider:
    id = "grok"
    display_name = "Grok"
    glyph = "grok"
    manage_url = "https://grok.com/?_s=usage"
    tracks_sessions = True

    def __init__(self, root=None):
        root = root or home(".grok")
        self._auth_path = f"{root}/auth.json"
        self._sessions_root = f"{root}/sessions"
        self.backoff_until = None

    def available(self):
        return exists(self._auth_path)

    def account(self):
        return {"plan": None, "source": "Grok"}

    def sessions_dir(self):
        return self._sessions_root

    def fetch(self, _previous=None):
        credential = self._credential()
        if credential["expiresAt"] is not None and credential["expiresAt"] <= _now_ms():
            return self._local(EXPIRED_NOTE)
        if self.backoff_until and self.backoff_until > _now_ms():
            raise ProviderError("rateLimited", RATE_LIMITED)
        credits = self._get(CREDITS_ENDPOINT, credential["token"])
        if credits["status"] in (401, 403):
            raise ProviderError("needsAuth", NEEDS_AUTH)
        if credits["status"] < 200 or credits["status"] >= 300:
            raise ProviderError("badResponse", f"Grok answered HTTP {credits['status']}")
        self.backoff_until = None
        windows = windows_from(credits["json"])
        if not windows:
            ledger = self._get(LEDGER_ENDPOINT, credential["token"])
            if 200 <= ledger["status"] < 300:
                windows = ledger_windows_from(ledger["json"])
        if not windows:
            return self._local(None)
        return {"windows": windows, "headlineID": "credits", "fidelity": "official"}

    def _local(self, note):
        snapshot = {
            "windows": [{
                "id": "requests",
                "label": "Requests today · no limit published",
                "usedFraction": None,
                "used": grok_requests_today(self._sessions_root),
                "resetsAt": None,
            }],
            "headlineID": "requests",
            "fidelity": "derived",
        }
        if note:
            snapshot["note"] = note
        return snapshot

    def _get(self, url, token):
        status, text, headers = request("GET", url, {
            "Authorization": f"Bearer {token}",
            "X-XAI-Token-Auth": "xai-grok-cli",
            "Accept": "application/json",
        })
        if status == 429:
            retry = _retry_after(headers)
            self.backoff_until = _now_ms() + max(60, retry) * 1000
            raise ProviderError("rateLimited", RATE_LIMITED)
        try:
            body = json.loads(text) if text else None
        except json.JSONDecodeError:
            body = None
        return {"status": status, "json": body}

    def _credential(self):
        entries = []
        for key, entry in (read_json(self._auth_path) or {}).items():
            if isinstance(entry, dict) and _is_trusted(key, entry):
                entries.append(entry)
        now = _now_ms()
        live = next((e for e in entries if _parse_ms(e.get("expires_at")) is None
                     or _parse_ms(e.get("expires_at")) > now), None)
        chosen = live or (entries[0] if entries else None)
        if not isinstance((chosen or {}).get("key"), str) or not chosen.get("key"):
            raise ProviderError("needsAuth", NEEDS_AUTH)
        return {"token": chosen["key"], "expiresAt": _parse_ms(chosen.get("expires_at"))}


def windows_from(body):
    config = (body or {}).get("config")
    if not isinstance(config, dict):
        return []
    resets_at = _as_dt(_parse_ms((config.get("currentPeriod") or {}).get("end"))
                       or _parse_ms(config.get("billingPeriodEnd")))
    overall = _fraction(config.get("creditUsagePercent"))
    if overall is not None:
        return [{
            "id": "credits",
            "label": _first_product_name(config) or "Grok Build",
            "usedFraction": overall,
            "resetsAt": resets_at,
        }]
    windows = []
    for product in config.get("productUsage") or []:
        fraction = _fraction((product or {}).get("usagePercent"))
        if fraction is None:
            continue
        name = _humanize(product["product"]) if isinstance(product.get("product"), str) else "Usage"
        windows.append({
            "id": "credits" if not windows else product.get("product") or name,
            "label": name,
            "usedFraction": fraction,
            "resetsAt": resets_at,
        })
    return windows


def ledger_windows_from(body):
    config = (body or {}).get("config") or {}
    try:
        limit = float((config.get("monthlyLimit") or {}).get("val"))
        used = float((config.get("used") or {}).get("val"))
    except (TypeError, ValueError):
        return []
    if not (limit > 0) or used < 0:
        return []
    return [{
        "id": "credits",
        "label": "Monthly limit",
        "usedFraction": used / limit,
        "resetsAt": _as_dt(_parse_ms(config.get("billingPeriodEnd"))),
    }]


def _first_product_name(config):
    name = ((config.get("productUsage") or [{}])[0] or {}).get("product")
    return _humanize(name) if isinstance(name, str) else None


def _humanize(name):
    out = []
    for i, ch in enumerate(name):
        if i and ch.isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out)


def _fraction(value):
    return value / 100 if isinstance(value, (int, float)) else None


def _is_trusted(key, entry):
    return key.startswith(TRUSTED_ISSUER) or entry.get("oidc_issuer") == TRUSTED_ISSUER


def _parse_ms(text):
    if not isinstance(text, str):
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def _as_dt(millis):
    if millis is None:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _retry_after(headers):
    try:
        return int(float(headers.get("Retry-After") or headers.get("retry-after") or 0))
    except ValueError:
        return 0
