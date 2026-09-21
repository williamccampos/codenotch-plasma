import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..credentials import kiro_region_from_arn, read_kiro_auth, read_kiro_cli_auth, read_kiro_usage_state
from ..httputil import ProviderError, home, read_json, request


_QCLIENT_RE = re.compile(r"GetUsageLimitsCommand.*\"output\":(\{.*\}),\"metadata\"")


class KiroProvider:
    id = "kiro"
    display_name = "Kiro"
    glyph = "kiro"
    manage_url = "https://app.kiro.dev/"
    tracks_sessions = False
    backoff_until = None

    def available(self):
        return (
            read_kiro_usage_state() is not None
            or read_kiro_auth() is not None
            or _usage_from_logs() is not None
        )

    def account(self):
        auth = read_kiro_auth() or {}
        return {"plan": auth.get("provider"), "source": auth.get("source") or "Kiro"}

    def fetch(self, _previous=None):
        for auth in (read_kiro_cli_auth(), read_kiro_auth()):
            if not auth:
                continue
            try:
                snapshot = self._fetch_api(auth)
                if snapshot:
                    return snapshot
            except ProviderError as exc:
                if exc.kind not in ("needsAuth", "badResponse"):
                    raise

        logged = _usage_from_logs()
        if logged:
            return logged

        local = read_kiro_usage_state()
        if local:
            windows = windows_from_local(local)
            if windows:
                return {
                    "windows": windows,
                    "headlineID": windows[0]["id"],
                    "fidelity": "local",
                    "note": "Kiro IDE cache (may be stale — open Kiro CLI /usage to refresh)",
                }

        raise ProviderError("needsAuth", "Sign in to Kiro CLI or Kiro IDE to read your usage")

    def _fetch_api(self, auth):
        token = auth.get("accessToken")
        profile_arn = auth.get("profileArn")
        if not token or not profile_arn:
            profile = None
            for sub in ("kiro.kiroagent", "kiro.kiroAgent"):
                profile = read_json(
                    home(".config", "Kiro", "User", "globalStorage", sub, "profile.json")
                )
                if profile:
                    break
            profile = profile or {}
            profile_arn = profile_arn or profile.get("arn")
        if not token or not profile_arn:
            raise ProviderError("needsAuth", "Kiro profile missing — open Kiro once to refresh it")
        region = kiro_region_from_arn(profile_arn)
        origins = ("AI_EDITOR", "KIRO_CLI", "AI_CLI", "CODING_ASSISTANT")
        base_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if auth.get("authMethod") == "IdC" or auth.get("provider") in (
            "IAM Identity Center", "AWS IAM Identity Center", "Kiro CLI",
        ):
            base_headers["TokenType"] = "EXTERNAL_IDP"
        hosts = (
            f"https://q.{region}.amazonaws.com",
            f"https://codewhisperer.{region}.amazonaws.com",
        )
        last_status = None
        for host in hosts:
            for origin in origins:
                query = (
                    f"origin={origin}&profileArn={quote(profile_arn, safe='')}"
                    f"&resourceType=AGENTIC_REQUEST"
                )
                for method, url, headers, body in (
                    ("GET", f"{host}/getUsageLimits?{query}", base_headers, None),
                    (
                        "POST",
                        f"{host}/getUsageLimits",
                        {
                            **base_headers,
                            "Content-Type": "application/x-amz-json-1.0",
                            "X-Amz-Target": "CodeWhispererRuntime.GetUsageLimits",
                        },
                        json.dumps({
                            "origin": origin,
                            "profileArn": profile_arn,
                            "resourceType": "AGENTIC_REQUEST",
                        }),
                    ),
                ):
                    status, text, _headers = request(method, url, headers, body=body)
                    last_status = status
                    if status in (401, 403) or status < 200 or status >= 300:
                        continue
                    payload = json.loads(text)
                    windows = windows_from_api(payload)
                    if not windows:
                        continue
                    snapshot = {
                        "windows": windows,
                        "headlineID": windows[0]["id"],
                        "fidelity": "official",
                    }
                    title = ((payload.get("subscriptionInfo") or {}).get("subscriptionTitle"))
                    source = auth.get("source") or "Kiro"
                    note_parts = [source.replace("-", " ").title() if isinstance(source, str) else "Kiro"]
                    if title:
                        note_parts.append(title)
                    snapshot["note"] = " · ".join(note_parts)
                    return snapshot
        if last_status in (401, 403):
            raise ProviderError("needsAuth", "Kiro sign-in expired — open Kiro CLI /usage once to refresh it")
        raise ProviderError("badResponse", f"Kiro answered HTTP {last_status or 'error'}")


def _usage_from_logs():
    best = None
    best_mtime = 0.0
    roots = (
        Path(home(".config", "Kiro", "logs")),
        Path(home(".kiro", "logs")),
    )
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("q-client.log"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < best_mtime:
                continue
            body = _parse_qclient_log(path)
            if body:
                best = body
                best_mtime = mtime
    if not best:
        return None
    windows = windows_from_api(best)
    if not windows:
        return None
    snapshot = {"windows": windows, "headlineID": windows[0]["id"], "fidelity": "log"}
    title = ((best.get("subscriptionInfo") or {}).get("subscriptionTitle"))
    if title:
        snapshot["note"] = title
    return snapshot


def _parse_qclient_log(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = None
    for line in text.splitlines():
        if "GetUsageLimitsCommand" not in line:
            continue
        found = _QCLIENT_RE.search(line)
        if found:
            match = found
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def windows_from_local(state):
    windows = []
    for item in state.get("usageBreakdowns") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("displayNamePlural") or item.get("displayName") or "Credits"
        used = item.get("currentUsage")
        limit = item.get("usageLimit")
        resets = _parse_date(item.get("resetDate"))
        frac = _fraction(used, limit, item.get("percentageUsed"))
        if frac is not None:
            windows.append({
                "id": str(item.get("type") or label).lower(),
                "label": label,
                "usedFraction": frac,
                "resetsAt": resets,
            })
        trial = item.get("freeTrialUsage") or {}
        t_frac = _fraction(
            trial.get("currentUsage"), trial.get("usageLimit"), trial.get("percentageUsed"),
        )
        if t_frac is not None:
            windows.append({
                "id": "bonus",
                "label": "Bonus credits",
                "usedFraction": t_frac,
                "resetsAt": _parse_date(trial.get("expiryDate")),
            })
    return windows


def windows_from_api(body):
    windows = []
    resets = _parse_date(body.get("nextDateReset"))
    for item in body.get("usageBreakdownList") or body.get("usageBreakdowns") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("displayNamePlural") or item.get("displayName") or "Credits"
        frac = _fraction(
            item.get("currentUsageWithPrecision", item.get("currentUsage")),
            item.get("usageLimitWithPrecision", item.get("usageLimit")),
            item.get("percentageUsed"),
        )
        if frac is None:
            continue
        windows.append({
            "id": str(item.get("type") or item.get("resourceType") or label).lower(),
            "label": label,
            "usedFraction": frac,
            "resetsAt": resets or _parse_date(item.get("resetDate") or item.get("nextDateReset")),
        })
    return windows


def _fraction(used, limit, percent=None):
    if isinstance(percent, (int, float)):
        value = float(percent)
        return max(0.0, min(1.0, value / 100 if value > 1 else value))
    try:
        used_v = float(used)
        limit_v = float(limit)
    except (TypeError, ValueError):
        return None
    if limit_v <= 0:
        return None
    return max(0.0, min(1.0, used_v / limit_v))


def _parse_date(text):
    if not text:
        return None
    try:
        if isinstance(text, str) and text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
