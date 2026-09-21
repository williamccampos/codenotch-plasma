import json
from datetime import datetime
from pathlib import Path

from .httputil import read_json


def archive_path():
    return Path.home() / ".cache" / "codenotch" / "readings.json"


def restore_snapshot(raw):
    if not raw or not isinstance(raw.get("windows"), list) or not isinstance(raw.get("fetchedAt"), (int, float)):
        return None
    windows = []
    for w in raw["windows"]:
        if not w or not (isinstance(w.get("usedFraction"), (int, float)) or isinstance(w.get("used"), (int, float))):
            continue
        item = {
            "id": w.get("id"),
            "label": w.get("label") or "",
            "usedFraction": w["usedFraction"] if isinstance(w.get("usedFraction"), (int, float)) else None,
            "resetsAt": _parse_date(w.get("resetsAt")),
        }
        if isinstance(w.get("used"), (int, float)):
            item["used"] = w["used"]
        if isinstance(w.get("remainingFraction"), (int, float)):
            item["remainingFraction"] = w["remainingFraction"]
        if isinstance(w.get("displayMode"), str):
            item["displayMode"] = w["displayMode"]
        windows.append(item)
    snapshot = {
        "windows": windows,
        "headlineID": raw.get("headlineID"),
        "fetchedAt": raw["fetchedAt"],
    }
    if isinstance(raw.get("displayMode"), str):
        snapshot["displayMode"] = raw["displayMode"]
    if isinstance(raw.get("note"), str):
        snapshot["note"] = raw["note"]
    if isinstance(raw.get("fidelity"), str):
        snapshot["fidelity"] = raw["fidelity"]
    if isinstance(raw.get("source"), str):
        snapshot["source"] = raw["source"]
    return snapshot


def load_archive():
    json_body = read_json(str(archive_path()))
    archive = {}
    if not isinstance(json_body, dict):
        return archive
    for pid, entry in json_body.items():
        if not isinstance(entry, dict):
            continue
        archive[pid] = {
            "snapshot": restore_snapshot(entry.get("snapshot")),
            "backoffUntil": entry.get("backoffUntil") if isinstance(entry.get("backoffUntil"), (int, float)) else None,
        }
    return archive


def save_archive(archive):
    path = archive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = json.loads(json.dumps(archive, default=_json_default))
    path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def _parse_date(text):
    if not text:
        return None
    if isinstance(text, datetime):
        return text
    try:
        if isinstance(text, str) and text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value))
