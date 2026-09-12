"""CLI credentials file: ``~/.ageval/credentials`` (mode 0600).

Wire format (JSON)::

    {
      "registry": {
        "url": "https://ageval.zjureal.com",
        "token": "ageval_…",
        "token_env": "AGEVAL_REGISTRY_TOKEN"   # optional locator; wins over token if set
      }
    }

Tokens never enter lock/evidence.

The operator knob is ``AGEVAL_REGISTRY_URL``. Unset, it is
``DEFAULT_REGISTRY_URL``. ``--registry-url`` (caller) still wins; a credentials
file ``url`` is a login pin (local compose) and sits under the env var.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REGISTRY_URL_ENV = "AGEVAL_REGISTRY_URL"
# Unset value of AGEVAL_REGISTRY_URL. Change here when the public origin moves.
DEFAULT_REGISTRY_URL = "https://ageval.zjureal.com"


@dataclass(frozen=True, slots=True)
class RegistryCredentials:
    url: str
    token: str | None


def default_credentials_path() -> Path:
    return Path.home() / ".ageval" / "credentials"


def registry_url_from_env() -> str | None:
    """Return ``AGEVAL_REGISTRY_URL`` when set, else None (caller uses the default)."""
    raw = os.environ.get(REGISTRY_URL_ENV, "").strip()
    return raw.rstrip("/") if raw else None


def load_credentials(path: Path | None = None) -> RegistryCredentials:
    """Load credentials; missing file / url still yields ``DEFAULT_REGISTRY_URL``."""
    cred_path = path or default_credentials_path()
    url: str | None = None
    token: str | None = None
    if cred_path.is_file():
        try:
            data = json.loads(cred_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        reg = data.get("registry") if isinstance(data, dict) else None
        if isinstance(reg, dict):
            raw_url = reg.get("url")
            if isinstance(raw_url, str) and raw_url.strip():
                url = raw_url.strip().rstrip("/")
            env_name = reg.get("token_env")
            if isinstance(env_name, str) and env_name:
                token = os.environ.get(env_name) or None
            if token is None:
                raw_tok = reg.get("token")
                if isinstance(raw_tok, str) and raw_tok:
                    token = raw_tok
    env_url = registry_url_from_env()
    if env_url:
        url = env_url
    env_tok = os.environ.get("AGEVAL_REGISTRY_TOKEN")
    if env_tok:
        token = env_tok
    if not url:
        url = DEFAULT_REGISTRY_URL
    return RegistryCredentials(url=url, token=token)


def write_credentials(
    *,
    url: str,
    token: str,
    path: Path | None = None,
) -> Path:
    """Write credentials file with mode 0600 (operator/bootstrap helper)."""
    cred_path = path or default_credentials_path()
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"registry": {"url": url.rstrip("/"), "token": token}}
    cred_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    cred_path.chmod(0o600)
    return cred_path
