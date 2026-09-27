"""GitHub OAuth Device Flow helpers for Registry login.

GitHub access tokens are used only to prove identity; the Registry then issues
its own API token (hashed at rest). GitHub tokens are never stored as Bearer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_USER_URL = "https://api.github.com/user"


@dataclass(frozen=True, slots=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    verification_uri_complete: str = ""


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    """GitHub user identity from ``GET /user`` (read:user scope)."""

    login: str
    id: int
    # Profile display name (API field ``name``); may be empty.
    name: str | None = None
    avatar_url: str | None = None


class GitHubOAuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _post_form(url: str, data: dict[str, str], *, timeout: float = 30.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        err = str(payload.get("error") or "http_error")
        desc = str(payload.get("error_description") or exc.reason or "HTTP error")
        raise GitHubOAuthError(err, desc) from exc
    except urllib.error.URLError as exc:
        raise GitHubOAuthError("github_unavailable", str(exc.reason)) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GitHubOAuthError("invalid_response", "non-JSON from GitHub") from exc


def request_device_code(*, client_id: str, scope: str = "read:user") -> DeviceCodeResponse:
    data = _post_form(
        GITHUB_DEVICE_CODE_URL,
        {"client_id": client_id, "scope": scope},
    )
    if "error" in data:
        raise GitHubOAuthError(str(data["error"]), str(data.get("error_description") or ""))
    verification_uri = str(data.get("verification_uri") or "https://github.com/login/device")
    user_code = str(data["user_code"])
    # Prefer GitHub's complete URI when present; always ensure user_code + skip
    # account picker. Multi-account sessions hit /login/device/select_account and
    # GitHub's default Continue drops bare ?user_code= — re-add both params.
    complete = str(data.get("verification_uri_complete") or "").strip()
    complete = _device_verify_url(complete or verification_uri, user_code)
    return DeviceCodeResponse(
        device_code=str(data["device_code"]),
        user_code=user_code,
        verification_uri=verification_uri,
        expires_in=int(data.get("expires_in") or 900),
        interval=int(data.get("interval") or 5),
        verification_uri_complete=complete,
    )


def _device_verify_url(base: str, user_code: str) -> str:
    """Build a device-activation URL that survives GitHub account picker redirects.

    GitHub multi-session flow: /login/device?user_code=X → select_account →
    /login/device?skip_account_picker=true (user_code stripped). Starting with
    both ``user_code`` and ``skip_account_picker=true`` avoids the empty form.
    """
    if not user_code:
        return base or "https://github.com/login/device"
    # Normalize to the canonical path; drop other query noise.
    parsed = urllib.parse.urlparse(base or "https://github.com/login/device")
    path = parsed.path or "/login/device"
    if path.rstrip("/").endswith("/select_account"):
        path = "/login/device"
    # Stable order for readability in CLI/logs.
    query = urllib.parse.urlencode(
        [
            ("user_code", user_code),
            ("skip_account_picker", "true"),
        ]
    )
    return urllib.parse.urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc or "github.com",
            path,
            "",
            query,
            "",
        )
    )


def poll_access_token(
    *,
    client_id: str,
    client_secret: str,
    device_code: str,
) -> str | None:
    """Return GitHub access_token, None if authorization_pending/slow_down.

    Raises GitHubOAuthError on terminal failure.
    """
    data = _post_form(
        GITHUB_ACCESS_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )
    if "access_token" in data:
        return str(data["access_token"])
    err = str(data.get("error") or "unknown")
    if err in {"authorization_pending", "slow_down"}:
        return None
    raise GitHubOAuthError(err, str(data.get("error_description") or err))


def build_web_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "read:user",
) -> str:
    """Browser OAuth authorize URL (Authorization Code flow; Hub SPA)."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_web_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> str:
    """Exchange web OAuth *code* for a GitHub access token."""
    data = _post_form(
        GITHUB_ACCESS_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    if "access_token" in data:
        return str(data["access_token"])
    err = str(data.get("error") or "unknown")
    raise GitHubOAuthError(err, str(data.get("error_description") or err))


def fetch_user(access_token: str, *, timeout: float = 30.0) -> GitHubIdentity:
    req = urllib.request.Request(
        GITHUB_USER_URL,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "ageval-registry",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise GitHubOAuthError("user_fetch_failed", f"status {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GitHubOAuthError("github_unavailable", str(exc.reason)) from exc
    data = json.loads(raw.decode("utf-8"))
    raw_name = data.get("name")
    name = str(raw_name).strip() if raw_name else None
    if name == "":
        name = None
    raw_avatar = data.get("avatar_url")
    avatar_url = str(raw_avatar).strip() if raw_avatar else None
    if avatar_url == "":
        avatar_url = None
    return GitHubIdentity(
        login=str(data["login"]),
        id=int(data["id"]),
        name=name,
        avatar_url=avatar_url,
    )
