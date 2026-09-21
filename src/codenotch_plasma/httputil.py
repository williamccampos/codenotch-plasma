"""Read-only JSON helpers and HTTPS fetches. Tokens are never logged."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def home(*parts):
    return str(Path.home().joinpath(*parts))


def exists(path):
    return os.path.exists(path)


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def request(method, url, headers=None, body=None, timeout=15):
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else body
    req = Request(url, data=data, method=method, headers=headers or {})
    req.add_header("User-Agent", "codenotch-plasma/0.1")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, body, dict(exc.headers or {})
    except URLError as exc:
        raise ProviderError("offline", "Couldn't reach the usage endpoint") from exc
