import json
from datetime import datetime

from ..credentials import (
    cursor_session_cookie,
    iter_cursor_agent_tokens,
    iter_cursor_browser_tokens,
    iter_cursor_ide_tokens,
)
from ..httputil import ProviderError, request


BASE_URL = "https://cursor.com"
_ENTERPRISE = frozenset({"enterprise", "team", "business"})


class CursorProviderBase:
    glyph = "cursor"
    manage_url = "https://cursor.com/dashboard?tab=usage"
    tracks_sessions = False
    backoff_until = None
    badge = None

    def account(self):
        return {"plan": None, "source": self.display_name}

    def fetch(self, _previous=None):
        tokens = list(self.iter_tokens())
        if not tokens:
            raise ProviderError("needsAuth", self._needs_auth_message())
        last_auth_error = None
        for token, source in tokens:
            try:
                snapshot = self._fetch_with_token(token, source)
                if self.accepts_snapshot(snapshot):
                    return snapshot
            except ProviderError as exc:
                if exc.kind == "needsAuth":
                    last_auth_error = exc
                    continue
                raise
        raise last_auth_error or ProviderError("needsAuth", self._needs_auth_message())

    def iter_tokens(self):
        raise NotImplementedError

    def accepts_snapshot(self, snapshot):
        raise NotImplementedError

    def _needs_auth_message(self):
        raise NotImplementedError

    def _headline_preference(self):
        return ("included", "overall", "plan", "pooled")

    def _fetch_with_token(self, token, source):
        cookie = self._cookie_header(token)
        status, text, _headers = request(
            "GET",
            f"{BASE_URL}/api/usage-summary",
            {"Cookie": cookie, "Accept": "application/json"},
        )
        if status in (401, 403):
            raise ProviderError(
                "needsAuth",
                "Cursor sign-in expired — open Cursor once to refresh it",
            )
        if status < 200 or status >= 300:
            raise ProviderError("badResponse", f"Cursor answered HTTP {status}")
        body = json.loads(text)
        windows = windows_from(body)
        if not windows:
            raise ProviderError("badResponse", "Cursor reported no usage windows")
        headline_id = _headline_id(windows, self._headline_preference())
        email = self._account_email(cookie)
        snapshot = {
            "windows": windows,
            "headlineID": headline_id,
            "source": source,
            "membershipType": body.get("membershipType"),
            "email": email,
        }
        note_parts = [self.display_name]
        plan = _plan_label(body.get("membershipType"))
        if plan:
            note_parts.append(plan)
        email = self._account_email(cookie)
        if email:
            note_parts.append(email)
        if source == "cursor-browser":
            note_parts.append("browser session")
        elif source == "cursor-ide":
            note_parts.append("Cursor IDE session")
        elif source == "cursor-agent":
            note_parts.append("Cursor agent session")
        snapshot["note"] = " · ".join(note_parts)
        return snapshot

    def _cookie_header(self, token):
        if "%3A%3A" in token or "::" in token:
            return f"WorkosCursorSessionToken={token}"
        return cursor_session_cookie(token)

    def _account_email(self, cookie):
        status, text, _ = request(
            "GET",
            f"{BASE_URL}/api/auth/me",
            {"Cookie": cookie, "Accept": "application/json"},
        )
        if status != 200 or not text:
            return None
        try:
            return json.loads(text).get("email")
        except json.JSONDecodeError:
            return None


class CursorPersonalProvider(CursorProviderBase):
    id = "cursor-personal"
    display_name = "Cursor Personal"
    badge = "personal"

    def _headline_preference(self):
        return ("plan", "included", "overall", "pooled")

    def available(self):
        return True

    def iter_tokens(self):
        yield from iter_cursor_ide_tokens()
        yield from iter_cursor_agent_tokens()

    def accepts_snapshot(self, snapshot):
        membership = str(snapshot.get("membershipType") or "").lower()
        return membership not in _ENTERPRISE

    def _needs_auth_message(self):
        return "Sign in to the Cursor IDE with your personal account"


class CursorCorpProvider(CursorProviderBase):
    id = "cursor-corp"
    display_name = "Cursor Corp"
    badge = "corp"
    manage_url = "https://cursor.com/dashboard"

    def _headline_preference(self):
        return ("overall", "pooled", "plan", "included")

    def available(self):
        return True

    def iter_tokens(self):
        yield from iter_cursor_browser_tokens()

    def accepts_snapshot(self, snapshot):
        membership = str(snapshot.get("membershipType") or "").lower()
        if membership in _ENTERPRISE:
            return True
        if snapshot.get("source") != "cursor-browser":
            return False
        email = (snapshot.get("email") or "").strip().lower()
        personal = (self._personal_email() or "").strip().lower()
        return bool(email and personal and email != personal)

    def _personal_email(self):
        for token, _source in iter_cursor_ide_tokens():
            try:
                cookie = self._cookie_header(token)
                email = self._account_email(cookie)
                if email:
                    return email
            except Exception:
                continue
        return None

    def _needs_auth_message(self):
        return "Sign in to cursor.com in Edge with your work account (not your personal email)"


# Backward-compatible alias.
CursorProvider = CursorPersonalProvider


def windows_from(body):
    windows = []
    billing_end = _parse_date(body.get("billingCycleEnd"))
    individual = body.get("individualUsage") or {}
    plan = individual.get("plan") or {}
    overall = individual.get("overall") or {}
    team = body.get("teamUsage") or {}
    pooled = team.get("pooled") or {}

    if isinstance(plan.get("used"), (int, float)) and isinstance(plan.get("limit"), (int, float)):
        limit = plan["limit"]
        if limit > 0:
            windows.append({
                "id": "included",
                "label": "Included monthly",
                "usedFraction": _clamp(plan["used"] / limit),
                "resetsAt": billing_end,
            })

    if plan:
        primary = _percent(plan.get("totalPercentUsed"), plan.get("used"), plan.get("limit"))
        if primary is not None:
            windows.append({
                "id": "plan",
                "label": "Total included usage",
                "usedFraction": primary,
                "resetsAt": billing_end,
            })
        auto = plan.get("autoPercentUsed")
        if isinstance(auto, (int, float)):
            windows.append({
                "id": "auto",
                "label": "Auto model",
                "usedFraction": _clamp(auto / 100 if auto > 1 else auto),
                "resetsAt": billing_end,
            })
        api = plan.get("apiPercentUsed")
        if isinstance(api, (int, float)):
            windows.append({
                "id": "api",
                "label": "API model",
                "usedFraction": _clamp(api / 100 if api > 1 else api),
                "resetsAt": billing_end,
            })
    elif overall:
        frac = _percent(None, overall.get("used"), overall.get("limit"))
        if frac is not None:
            windows.append({
                "id": "overall",
                "label": "Your allocation",
                "usedFraction": frac,
                "resetsAt": billing_end,
            })

    if pooled:
        frac = _percent(None, pooled.get("used"), pooled.get("limit"))
        if frac is not None:
            windows.append({
                "id": "pooled",
                "label": "Team pooled usage",
                "usedFraction": frac,
                "resetsAt": billing_end,
            })

    on_demand = individual.get("onDemand") or team.get("onDemand") or {}
    if on_demand.get("enabled") is not False:
        frac = _percent(None, on_demand.get("used"), on_demand.get("limit"))
        if frac is not None:
            windows.append({
                "id": "ondemand",
                "label": "On-demand spend",
                "usedFraction": frac,
                "resetsAt": billing_end,
            })
    return windows


def _headline_id(windows, preferred=("included", "overall", "plan", "pooled")):
    for wid in preferred:
        if any(w.get("id") == wid for w in windows):
            return wid
    return windows[0]["id"] if windows else None


def _percent(total_percent, used, limit):
    if isinstance(total_percent, (int, float)):
        return _clamp(total_percent / 100 if total_percent > 1 else total_percent)
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        return _clamp(used / limit)
    return None


def _clamp(value):
    return max(0.0, min(1.0, float(value)))


def _parse_date(text):
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _plan_label(membership):
    if not membership:
        return None
    mapping = {
        "enterprise": "Cursor Enterprise",
        "pro": "Cursor Pro",
        "hobby": "Cursor Hobby",
        "team": "Cursor Team",
        "business": "Cursor Business",
    }
    return mapping.get(str(membership).lower(), f"Cursor {str(membership).title()}")
