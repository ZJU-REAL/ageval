"""Device / web session auth (GitHub OAuth lives in oauth_github)."""

from __future__ import annotations

import os
import secrets
import sys
import time
from typing import Any

from services.registry.errors import RegistryAppError
from services.registry.oauth_github import (
    GitHubOAuthError,
    build_web_authorize_url,
    exchange_web_code,
    fetch_user,
    poll_access_token,
    request_device_code,
)
from services.registry.store import DEFAULT_LOGIN_SCOPES, TokenInfo


class AuthService:
    def __init__(
        self,
        tokens: Any,
        *,
        orgs: Any,
        github_client_id: str | None,
        github_client_secret: str | None,
        github_login_allowlist: frozenset[str],
    ) -> None:
        self.tokens = tokens
        self.orgs = orgs
        self.github_client_id = github_client_id
        self.github_client_secret = github_client_secret
        self.github_login_allowlist = github_login_allowlist
        self.oauth_web_states: dict[str, dict[str, Any]] = {}

    def auth_for(self, raw_token: str | None) -> TokenInfo:
        return self.tokens.auth_for(raw_token)

    def issue_registry_session(self, identity: Any) -> dict[str, Any]:
        allow = self.github_login_allowlist
        login = str(getattr(identity, "login", "") or "")
        if allow and login.casefold() not in {u.casefold() for u in allow}:
            raise RegistryAppError(
                "login_not_allowed",
                f"GitHub user {login!r} is not on AGEVAL_GITHUB_LOGIN_ALLOWLIST "
                f"(allowed: {', '.join(sorted(allow))})",
                http_status=403,
            )
        api_token = secrets.token_urlsafe(32)
        self.tokens.add(api_token, DEFAULT_LOGIN_SCOPES, github_user=login)
        display_name = getattr(identity, "name", None) or ""
        avatar_url = getattr(identity, "avatar_url", None) or ""
        github_id = getattr(identity, "id", None)
        try:
            upsert = self.orgs.upsert_user_profile
            if callable(upsert):
                upsert(
                    user_id=login,
                    display_name=str(display_name or ""),
                    avatar_url=str(avatar_url or ""),
                    github_id="" if github_id is None else str(github_id),
                )
        except Exception:  # noqa: BLE001
            pass
        payload: dict[str, Any] = {
            "token": api_token,
            "token_type": "bearer",
            "scopes": sorted(DEFAULT_LOGIN_SCOPES),
            "github_user": login,
        }
        if github_id is not None:
            payload["github_id"] = github_id
        if display_name:
            payload["github_name"] = str(display_name)
        if avatar_url:
            payload["avatar_url"] = str(avatar_url)
        return payload

    def device_code(self) -> dict[str, Any]:
        if not self.github_client_id:
            raise RegistryAppError(
                "oauth_not_configured",
                "AGEVAL_GITHUB_CLIENT_ID not set",
                http_status=503,
            )
        try:
            dc = request_device_code(client_id=self.github_client_id)
        except GitHubOAuthError as exc:
            raise RegistryAppError(exc.code, exc.message, http_status=502) from exc
        from services.registry.oauth_github import _device_verify_url

        return {
            "device_code": dc.device_code,
            "user_code": dc.user_code,
            "verification_uri": dc.verification_uri,
            "expires_in": dc.expires_in,
            "interval": dc.interval,
            "verification_uri_complete": _device_verify_url(
                dc.verification_uri_complete or dc.verification_uri,
                dc.user_code,
            ),
        }

    def device_poll(self, *, device_code: str) -> tuple[int, dict[str, Any]]:
        if not self.github_client_id or not self.github_client_secret:
            raise RegistryAppError(
                "oauth_not_configured",
                "GitHub OAuth client not configured",
                http_status=503,
            )
        if not device_code:
            raise RegistryAppError("invalid_request", "device_code required", http_status=400)
        try:
            gh_token = poll_access_token(
                client_id=self.github_client_id,
                client_secret=self.github_client_secret,
                device_code=device_code,
            )
        except GitHubOAuthError as exc:
            sys.stderr.write(f"oauth poll github_error code={exc.code} msg={exc.message!r}\n")
            raise RegistryAppError(exc.code, exc.message, http_status=400) from exc
        if gh_token is None:
            return 202, {"status": "authorization_pending", "message": "waiting for user"}
        try:
            identity = fetch_user(gh_token)
        except GitHubOAuthError as exc:
            sys.stderr.write(f"oauth fetch_user failed code={exc.code} msg={exc.message!r}\n")
            raise RegistryAppError(exc.code, exc.message, http_status=502) from exc
        sys.stderr.write(
            f"oauth poll authorized github_user={identity.login!r} (issuing registry token)\n"
        )
        return 200, self.issue_registry_session(identity)

    def web_start(self, *, redirect_uri: str) -> dict[str, Any]:
        if not self.github_client_id:
            raise RegistryAppError(
                "oauth_not_configured",
                "AGEVAL_GITHUB_CLIENT_ID not set",
                http_status=503,
            )
        if not self._allowed_web_redirect(redirect_uri):
            raise RegistryAppError(
                "invalid_redirect_uri",
                "redirect_uri not allowed "
                "(default: localhost Vite :5174 and compose Hub :8080; "
                "extend via AGEVAL_GITHUB_WEB_REDIRECT_URIS)",
                http_status=400,
            )
        self._purge_stale_oauth_states()
        state_token = secrets.token_urlsafe(24)
        self.oauth_web_states[state_token] = {
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
        }
        sys.stderr.write(
            f"oauth web start state={state_token[:8]}... "
            f"redirect={redirect_uri!r} pending={len(self.oauth_web_states)}\n"
        )
        url = build_web_authorize_url(
            client_id=self.github_client_id,
            redirect_uri=redirect_uri,
            state=state_token,
        )
        return {"authorize_url": url, "state": state_token}

    def web_callback(self, *, code: str, state: str, redirect_uri: str) -> dict[str, Any]:
        if not self.github_client_id or not self.github_client_secret:
            raise RegistryAppError(
                "oauth_not_configured",
                "GitHub OAuth client not configured",
                http_status=503,
            )
        if not code or not state:
            raise RegistryAppError(
                "invalid_request",
                "code and state required",
                http_status=400,
            )
        self._purge_stale_oauth_states()
        pending = self.oauth_web_states.get(state)
        if pending is None:
            raise RegistryAppError(
                "invalid_state",
                "unknown or expired OAuth state; start login again",
                http_status=400,
            )
        expected_redirect = str(pending.get("redirect_uri") or "")
        if redirect_uri and redirect_uri != expected_redirect:
            raise RegistryAppError(
                "invalid_redirect_uri",
                "redirect_uri mismatch",
                http_status=400,
            )
        try:
            gh_token = exchange_web_code(
                client_id=self.github_client_id,
                client_secret=self.github_client_secret,
                code=code,
                redirect_uri=expected_redirect,
            )
            identity = fetch_user(gh_token)
        except GitHubOAuthError as exc:
            sys.stderr.write(f"oauth web callback failed code={exc.code} msg={exc.message!r}\n")
            raise RegistryAppError(exc.code, exc.message, http_status=400) from exc
        self.oauth_web_states.pop(state, None)
        sys.stderr.write(
            f"oauth web authorized github_user={identity.login!r} (issuing registry token)\n"
        )
        return self.issue_registry_session(identity)

    def _allowed_web_redirect(self, redirect_uri: str) -> bool:
        uri = (redirect_uri or "").strip()
        if not uri:
            return False
        defaults = {
            "http://127.0.0.1:5174/login/callback",
            "http://localhost:5174/login/callback",
            "http://127.0.0.1:8080/login/callback",
            "http://localhost:8080/login/callback",
        }
        extra = os.environ.get("AGEVAL_GITHUB_WEB_REDIRECT_URIS") or ""
        for part in extra.split(","):
            p = part.strip()
            if p:
                defaults.add(p)
        return uri in defaults

    def _purge_stale_oauth_states(self, *, ttl_s: float = 600.0) -> None:
        now_ts = time.time()
        stale = [
            k
            for k, v in self.oauth_web_states.items()
            if now_ts - float(v.get("created_at") or 0) > ttl_s
        ]
        for k in stale:
            self.oauth_web_states.pop(k, None)
