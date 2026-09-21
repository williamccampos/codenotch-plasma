import base64
import json
import subprocess
from datetime import datetime, timezone

from ..httputil import ProviderError, exists, home, request
from ..sessions import read_antigravity_activity
from .antigravity_bridge import read_quota, windows_from_api


LOAD_ENDPOINT = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
QUOTA_ENDPOINT = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
KEYRING_PREFIX = "go-keyring-base64:"
EXPIRED_NOTE = "Sign-in expired · run agy to refresh"
BRIDGE_NOTE = "Open agy to read the limits"


class AntigravityProvider:
    id = "antigravity"
    display_name = "Antigravity"
    glyph = "antigravity"
    manage_url = "https://antigravity.google"
    tracks_sessions = True
    backoff_until = None

    def __init__(self, cli_root=None, ide_root=None):
        self._roots = [
            cli_root or home(".gemini", "antigravity-cli"),
            ide_root or home(".gemini", "antigravity"),
        ]
        self._brains = [f"{root}/brain" for root in self._roots]
        self._token_path = f"{self._roots[0]}/antigravity-oauth-token"
        self._tier = None

    def available(self):
        return any(exists(root) for root in self._roots)

    def account(self):
        return {"plan": self._tier or "Personal", "source": "Antigravity"}

    def brains_dirs(self):
        return self._brains

    def fetch(self, previous=None):
        bridge = read_quota()
        if bridge.get("windows"):
            return {
                "windows": bridge["windows"],
                "headlineID": bridge["headlineID"],
                "fidelity": "official",
                "source": "bridge",
            }
        missing = None if bridge.get("found") else BRIDGE_NOTE

        token = self._token()
        if token["expiresAt"] is not None and token["expiresAt"] <= _now_ms():
            return self._local(_join_notes(EXPIRED_NOTE, missing), previous)
        if self.backoff_until and self.backoff_until > _now_ms():
            raise ProviderError("rateLimited", "Antigravity asked us to wait before reading again")

        load = self._post(LOAD_ENDPOINT, token["accessToken"], {"metadata": {"pluginType": "GEMINI"}})
        if load["status"] in (401, 403):
            return self._local(_join_notes(EXPIRED_NOTE, missing), previous)
        if load["status"] < 200 or load["status"] >= 300:
            raise ProviderError("badResponse", f"Antigravity answered HTTP {load['status']}")
        self.backoff_until = None
        self._tier = _tier_from(load.get("json")) or self._tier

        quota = self._post(QUOTA_ENDPOINT, token["accessToken"], {})
        windows = windows_from_api(quota.get("json")) if 200 <= quota["status"] < 300 else []
        if not windows:
            return self._local(missing, previous)
        return {"windows": windows, "headlineID": windows[0]["id"], "fidelity": "official"}

    def _local(self, note, previous=None):
        if (previous or {}).get("source") == "bridge":
            raise ProviderError("offline", "agy is not running · open it to refresh")
        activity = read_antigravity_activity(self._brains)
        snapshot = {
            "windows": [{
                "id": "requests",
                "label": "Requests today · no limit published",
                "usedFraction": None,
                "used": activity["requestsToday"],
                "resetsAt": None,
            }],
            "headlineID": "requests",
            "fidelity": "derived",
        }
        if note:
            snapshot["note"] = note
        return snapshot

    def _post(self, url, access_token, body):
        status, text, headers = request(
            "POST", url,
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json.dumps(body),
        )
        if status == 429:
            retry = _retry_after(headers)
            self.backoff_until = _now_ms() + max(60, retry) * 1000
            raise ProviderError("rateLimited", "Antigravity asked us to wait before reading again")
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = None
        return {"status": status, "json": parsed}

    def _token(self):
        raw = _keyring_secret() or _file_secret(self._token_path)
        token = _decode_credential(raw)
        if not token or not token.get("access_token"):
            raise ProviderError("needsAuth", "Sign in to Antigravity (run `agy` once) to read your usage")
        expiry = token.get("expiry")
        expires_at = None
        if expiry:
            try:
                expires_at = int(datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                expires_at = None
        return {"accessToken": token["access_token"], "expiresAt": expires_at}


def _keyring_secret():
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True, text=True, timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _file_secret(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _decode_credential(raw):
    if not raw:
        return None
    text = raw.strip()
    if text.startswith(KEYRING_PREFIX):
        try:
            text = base64.urlsafe_b64decode(text[len(KEYRING_PREFIX):] + "==").decode("utf-8")
        except Exception:
            return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    token = data.get("token") if isinstance(data, dict) else None
    return token if isinstance(token, dict) else data


def _join_notes(*notes):
    kept = [n for n in notes if n]
    return " · ".join(kept) if kept else None


def _tier_from(json_body):
    tiers = json_body.get("allowedTiers") if isinstance(json_body, dict) else None
    tiers = tiers if isinstance(tiers, list) else []
    current = (json_body or {}).get("currentTier") or {}
    if current.get("name"):
        return current["name"]
    named = next((t for t in tiers if t.get("id") == current.get("id")), None)
    return (named or next((t for t in tiers if t.get("isDefault")), None) or (tiers[0] if tiers else None) or {}).get("name")


def _retry_after(headers):
    try:
        return int(float(headers.get("Retry-After") or headers.get("retry-after") or 0))
    except ValueError:
        return 0


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)
