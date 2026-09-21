"""Live activity from local session files (sessions.js, simplified)."""

import json
import os
from datetime import datetime
from pathlib import Path


def summarize(sessions):
    if not sessions:
        return None
    state = "idle"
    if any(s.get("state") == "waiting" for s in sessions):
        state = "waiting"
    elif any(s.get("state") == "busy" for s in sessions):
        state = "working"
    return {"state": state, "sessions": sessions}


def read_claude_sessions(directory):
    root = Path(directory)
    if not root.is_dir():
        return []
    sessions = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        record = _decode_claude(data)
        if record and _is_alive(record["pid"], record["procStart"]):
            sessions.append(record["session"])
    sessions.sort(key=lambda s: s.get("since") or 0, reverse=True)
    return sessions


def grok_requests_today(root):
    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    total = 0
    base = Path(root)
    if not base.is_dir():
        return 0
    for updates in base.glob("*/*/updates.jsonl"):
        try:
            if updates.stat().st_mtime < day_start:
                continue
            with updates.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = ev.get("timestamp") or ev.get("time") or ev.get("createdAt")
                    if isinstance(ts, (int, float)):
                        millis = ts if ts > 1e12 else ts * 1000
                    elif isinstance(ts, str):
                        try:
                            millis = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000
                        except ValueError:
                            continue
                    else:
                        continue
                    if millis >= day_start * 1000:
                        total += 1
        except OSError:
            continue
    return total


def _decode_claude(json_body):
    if not json_body or not isinstance(json_body.get("pid"), (int, float)):
        return None
    cwd = json_body.get("cwd")
    if not isinstance(cwd, str):
        return None
    raw = json_body.get("status")
    tempo = json_body.get("tempo")
    state = "idle"
    if tempo == "blocked" or raw == "waiting":
        state = "waiting"
    elif tempo == "active" or raw == "busy":
        state = "busy"
    folder = [p for p in cwd.split("/") if p][-1] if cwd else cwd
    millis = json_body.get("statusUpdatedAt") or json_body.get("updatedAt")
    return {
        "pid": int(json_body["pid"]),
        "procStart": json_body.get("procStart") if isinstance(json_body.get("procStart"), str) else None,
        "session": {
            "id": f"claude.{int(json_body['pid'])}",
            "name": json_body.get("name") or folder,
            "detail": f"{_surface(json_body.get('entrypoint'))} · {folder}",
            "state": state,
            "waitingFor": json_body.get("waitingFor") or json_body.get("needs"),
            "since": millis if isinstance(millis, (int, float)) else int(datetime.now().timestamp() * 1000),
        },
    }


def _surface(entrypoint):
    return {
        "claude-desktop": "Desktop",
        "claude-desktop-3p": "Desktop",
        "claude-vscode": "VS Code",
        "local-agent": "Agent",
    }.get(entrypoint, "Terminal")


def _is_alive(pid, proc_start):
    if not os.path.isdir(f"/proc/{pid}"):
        return False
    if not proc_start or not str(proc_start).isdigit():
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="ignore")
        rest = stat[stat.rfind(")") + 2 :].split(" ")
        return rest[19] == proc_start
    except (OSError, IndexError):
        return True
