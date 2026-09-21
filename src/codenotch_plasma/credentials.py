"""Read-only helpers for local IDE credential stores (no writes, no logging)."""

import json
import sqlite3
from pathlib import Path

from .httputil import home, read_json


def read_vscdb_value(db_path, key):
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _yield_unique(tokens, seen):
    for token, source in tokens:
        token = (token or "").strip()
        if token and token not in seen:
            seen.add(token)
            yield token, source


def iter_cursor_ide_tokens():
    seen = set()
    db = home(".config", "Cursor", "User", "globalStorage", "state.vscdb")
    for key in ("cursorAuth/accessToken", "cursorAuth/token"):
        value = read_vscdb_value(db, key)
        if isinstance(value, str) and value.strip():
            token = value.strip()
        elif value:
            token = str(value).strip()
        else:
            continue
        yield from _yield_unique([(token, "cursor-ide")], seen)


def iter_cursor_agent_tokens():
    seen = set()
    auth = read_json(home(".config", "cursor", "auth.json")) or {}
    yield from _yield_unique([(auth.get("accessToken"), "cursor-agent")], seen)


def iter_cursor_browser_tokens():
    seen = set()
    for cookie in _browser_cursor_cookies():
        yield from _yield_unique([(cookie, "cursor-browser")], seen)


def iter_cursor_access_tokens():
    """All Cursor tokens, browser last (legacy helper)."""
    seen = set()
    for iterator in (iter_cursor_ide_tokens, iter_cursor_agent_tokens, iter_cursor_browser_tokens):
        yield from _yield_unique(iterator(), seen)


def _browser_cursor_cookies():
    try:
        import browser_cookie3
    except ImportError:
        return []
    found = []
    seen = set()

    def add(value):
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            found.append(value)

    loaders = ("edge", "chrome", "chromium", "brave", "firefox")
    for loader_name in loaders:
        loader = getattr(browser_cookie3, loader_name, None)
        if loader is None:
            continue
        try:
            jar = loader(domain_name="cursor.com")
        except Exception:
            jar = None
        if jar is not None:
            for cookie in jar:
                if cookie.name == "WorkosCursorSessionToken" and cookie.value:
                    add(cookie.value)

    edge_root = Path(home(".config", "microsoft-edge"))
    if edge_root.is_dir():
        for cookie_file in edge_root.glob("*/Cookies"):
            try:
                jar = browser_cookie3.chrome(
                    cookie_file=str(cookie_file),
                    domain_name="cursor.com",
                )
            except Exception:
                continue
            for cookie in jar:
                if cookie.name == "WorkosCursorSessionToken" and cookie.value:
                    add(cookie.value)
    return found


def read_cursor_access_token():
    for token, source in iter_cursor_access_tokens():
        return token, source
    return None, None


def cursor_session_cookie(token):
    user_id = _cursor_user_id(token)
    return f"WorkosCursorSessionToken={user_id}%3A%3A{token}"


def _cursor_user_id(token):
    payload = _jwt_payload(token)
    sub = (payload or {}).get("sub") or ""
    if "|" in sub:
        return sub.rsplit("|", 1)[-1]
    return sub


def _jwt_payload(token):
    try:
        import base64
        part = token.split(".")[1]
        part += "=" * ((4 - len(part) % 4) % 4)
        raw = base64.urlsafe_b64decode(part.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def read_kiro_usage_state():
    db = home(".config", "Kiro", "User", "globalStorage", "state.vscdb")
    for key in ("kiro.resourceNotifications.usageState", "kiro.kiroAgent"):
        value = read_vscdb_value(db, key)
        if not value:
            continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                continue
        if not isinstance(value, dict):
            continue
        if "usageBreakdowns" in value:
            return value
        nested = value.get("kiro.resourceNotifications.usageState")
        if isinstance(nested, dict) and nested.get("usageBreakdowns"):
            return nested
    return None


def read_kiro_cli_auth():
    db = Path(home(".local", "share", "kiro-cli", "data.sqlite3"))
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        token_row = conn.execute(
            "SELECT value FROM auth_kv WHERE key = ?", ("kirocli:odic:token",)
        ).fetchone()
        profile_row = conn.execute(
            "SELECT value FROM state WHERE key = ?", ("api.codewhisperer.profile",)
        ).fetchone()
        region_row = conn.execute(
            "SELECT value FROM state WHERE key = ?", ("auth.idc.region",)
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not token_row:
        return None
    try:
        token_data = json.loads(token_row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    access = token_data.get("accessToken") or token_data.get("access_token")
    if not access:
        return None
    profile = {}
    if profile_row:
        try:
            profile = json.loads(profile_row[0]) or {}
        except (TypeError, json.JSONDecodeError):
            profile = {}
    region = "us-east-1"
    if region_row and region_row[0]:
        try:
            region = json.loads(region_row[0])
        except (TypeError, json.JSONDecodeError):
            region = str(region_row[0]).strip() or region
    return {
        "accessToken": access,
        "profileArn": profile.get("arn"),
        "authMethod": "IdC",
        "provider": "Kiro CLI",
        "region": region,
        "source": "kiro-cli",
    }


def read_kiro_auth():
    cli = read_kiro_cli_auth()
    if cli:
        return cli
    cache = Path(home(".aws", "sso", "cache"))
    if cache.is_dir():
        for path in sorted(cache.glob("kiro-auth-token.json"), reverse=True):
            data = read_json(str(path))
            if isinstance(data, dict) and data.get("accessToken"):
                return data
        for path in cache.iterdir():
            if not path.is_file():
                continue
            data = read_json(str(path))
            if isinstance(data, dict) and data.get("accessToken") and (
                "profileArn" in data or data.get("provider")
            ):
                return data
    return None


def kiro_region_from_arn(arn):
    if not arn or not isinstance(arn, str):
        return "us-east-1"
    parts = arn.split(":")
    if len(parts) > 3 and parts[3]:
        return parts[3]
    return "us-east-1"
