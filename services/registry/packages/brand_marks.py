"""Closed marketplace icon_key allowlist and GitHub login (design/12)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from services.registry.errors import RegistryAppError

_PATH = Path(__file__).with_name("brand_marks.json")
ALLOWED_KEYS: frozenset[str] = frozenset(
    json.loads(_PATH.read_text(encoding="utf-8")),
)

_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"([A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})"
    r"(?:/|$)",
    re.IGNORECASE,
)


def normalize_icon_key(raw: object) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "unknown icon_key", http_status=400)
    key = raw.strip().lower()
    if not key:
        return ""
    if key not in ALLOWED_KEYS:
        raise RegistryAppError("invalid_request", "unknown icon_key", http_status=400)
    return key


def normalize_icon_github(raw: object) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "unknown icon_github", http_status=400)
    text = raw.strip()
    if not text:
        return ""
    match = _URL.match(text)
    login = match.group(1) if match else text
    if login.startswith("@"):
        login = login[1:]
    if not _LOGIN.fullmatch(login):
        raise RegistryAppError("invalid_request", "unknown icon_github", http_status=400)
    return login
