"""Ask Antigravity's local language server for quota (ported from antigravity-bridge.js)."""

import json
import os
import re
import ssl
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

SERVICE = "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
CSRF_HEADER = "x-codeium-csrf-token"
BODY = b'{"forceRefresh":true}'
TIMEOUT = 5
_UNVERIFIED = ssl.create_default_context()
_UNVERIFIED.check_hostname = False
_UNVERIFIED.verify_mode = ssl.CERT_NONE
_cached = None


def discover():
    by_inode = _listening_ports()
    endpoints = []
    for pid in _process_ids():
        token = _token_for(pid)
        if not token:
            continue
        for port in _ports_of(pid, by_inode):
            endpoints.append({"pid": pid, "port": port, "csrf": token["csrf"]})
    return endpoints


def read_quota():
    global _cached
    try:
        if _cached:
            windows = _quota(_cached)
            if windows:
                return _summarize(windows)
            _cached = None
        endpoints = discover()
        for endpoint in endpoints:
            windows = _quota(endpoint)
            if windows:
                _cached = endpoint
                return _summarize(windows)
        return {"windows": [], "headlineID": None, "found": len(endpoints) > 0}
    except Exception:
        return {"windows": [], "headlineID": None, "found": False}


def _summarize(windows):
    ids = {w["id"] for w in windows}
    headline = "gemini-5h" if "gemini-5h" in ids else (
        "gemini-weekly" if "gemini-weekly" in ids else windows[0]["id"]
    )
    return {"windows": windows, "headlineID": headline, "found": True}


def _quota(endpoint):
    address = f"127.0.0.1:{endpoint['port']}{SERVICE}"
    plain = _post(f"http://{address}", endpoint.get("csrf"))
    if plain["status"] == 200:
        return _windows_from(plain["text"])
    if plain["status"] not in (0, 400, 404):
        return []
    secure = _post(f"https://{address}", endpoint.get("csrf"))
    return _windows_from(secure["text"]) if secure["status"] == 200 else []


def _post(url, csrf):
    headers = {"Content-Type": "application/json", "User-Agent": "codenotch-plasma/0.1"}
    if csrf:
        headers[CSRF_HEADER] = csrf
    req = Request(url, data=BODY, method="POST", headers=headers)
    try:
        with urlopen(req, timeout=TIMEOUT, context=_UNVERIFIED if url.startswith("https") else None) as resp:
            return {"status": resp.status, "text": resp.read().decode("utf-8", "replace")}
    except Exception:
        return {"status": 0, "text": ""}


def _windows_from(text):
    try:
        json_body = json.loads(text)
    except json.JSONDecodeError:
        return []
    windows = []
    for group in (json_body.get("response") or {}).get("groups") or []:
        for bucket in group.get("buckets") or []:
            remaining = bucket.get("remainingFraction")
            if not isinstance(remaining, (int, float)) or remaining < 0 or remaining > 1:
                continue
            resets_at = bucket.get("resetTime")
            reset_dt = None
            if resets_at:
                try:
                    reset_dt = resets_at if hasattr(resets_at, "timestamp") else None
                    if isinstance(resets_at, str):
                        from datetime import datetime
                        reset_dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    reset_dt = None
            windows.append({
                "id": bucket.get("bucketId") or group.get("displayName") or "quota",
                "label": _label_for(group, bucket),
                "usedFraction": 1 - remaining,
                "resetsAt": reset_dt,
            })
    return windows


def _label_for(group, bucket):
    models = re.sub(r"\s+and\s+", " & ", re.sub(r"\s+models?$", "", group.get("displayName") or ""), flags=re.I)
    window = {
        "weekly": "Weekly",
        "5h": "5 hours",
    }.get(bucket.get("window")) or re.sub(
        r"\s*Limit\s*Remaining$", "", bucket.get("displayName") or "", flags=re.I
    )
    parts = [p for p in (models, window) if p]
    return " · ".join(parts) if parts else "Usage"


def _process_ids():
    pids = []
    proc = Path("/proc")
    if not proc.is_dir():
        return pids
    for entry in proc.iterdir():
        if entry.name.isdigit():
            pids.append(entry.name)
    return pids


def _token_for(pid):
    comm_path = Path(f"/proc/{pid}/comm")
    try:
        if comm_path.read_text(encoding="utf-8", errors="ignore").strip() == "agy":
            return {"csrf": None}
    except OSError:
        pass
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    text = [part.decode("utf-8", errors="ignore") for part in argv]
    if not any("language_server" in arg for arg in text):
        return None
    if "--csrf_token" in text:
        idx = text.index("--csrf_token")
        if idx + 1 < len(text) and text[idx + 1]:
            return {"csrf": text[idx + 1]}
    return None


def _ports_of(pid, by_inode):
    ports = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    if not fd_dir.is_dir():
        return []
    for link in fd_dir.iterdir():
        try:
            target = os.readlink(link)
        except OSError:
            continue
        match = re.match(r"socket:\[(\d+)\]", target)
        if not match:
            continue
        port = by_inode.get(match.group(1))
        if port is not None:
            ports.add(port)
    return list(ports)


def _listening_ports():
    by_inode = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.strip().split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            local = fields[1]
            port = int(local.split(":")[-1], 16)
            if port > 0:
                by_inode[fields[9]] = port
    return by_inode


def windows_from_api(json_body):
    """Quota buckets from Google's retrieveUserQuotaSummary endpoint."""
    if not json_body:
        return []
    buckets = []
    for group in json_body.get("quotaGroups") or []:
        buckets.extend(group.get("buckets") or [])
    buckets.extend(json_body.get("buckets") or [])
    windows = []
    for bucket in buckets:
        used = bucket.get("used")
        limit = bucket.get("limit")
        if not isinstance(limit, (int, float)) or limit <= 0:
            continue
        if not isinstance(used, (int, float)) or used < 0 or used > limit * 1.5:
            continue
        resets_at = bucket.get("resetTime")
        reset_dt = None
        if resets_at:
            try:
                from datetime import datetime
                reset_dt = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
            except ValueError:
                reset_dt = None
        windows.append({
            "id": bucket.get("name") or bucket.get("displayName"),
            "label": bucket.get("displayName") or bucket.get("name") or "Usage",
            "usedFraction": used / limit,
            "resetsAt": reset_dt,
        })
    return windows
