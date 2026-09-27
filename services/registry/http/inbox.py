"""Inbox HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result


class InboxHandlers:
    def _list_requests(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        inbox = str((qs.get("inbox") or [""])[0]).strip().lower() in {"1", "true", "yes"}
        suite_run_id = str((qs.get("suite_run_id") or [""])[0]).strip()
        try:
            if inbox:
                payload = self.state.requests.inbox(auth=auth)
            elif suite_run_id:
                payload = self.state.requests.list_for_suite(suite_run_id=suite_run_id, auth=auth)
            else:
                payload = self.state.requests.inbox(auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _apply_request(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"kind", "suite_run_id", "agent", "canonical_model"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        kind = str(body.get("kind") or "").strip()
        suite_run_id = str(body.get("suite_run_id") or "").strip()
        agent_raw = body.get("agent")
        agent = str(agent_raw).strip() if isinstance(agent_raw, str) else None
        canonical_raw = body.get("canonical_model")
        canonical_model = str(canonical_raw).strip() if isinstance(canonical_raw, str) else None
        try:
            payload = self.state.requests.apply(
                kind=kind,
                suite_run_id=suite_run_id,
                auth=auth,
                agent=agent,
                canonical_model=canonical_model,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _decide_requests(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"ids", "action", "canonical_model"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        ids = body.get("ids")
        if not isinstance(ids, list):
            return json_result(400, {"error": "invalid_request", "message": "ids required"})
        action = str(body.get("action") or "").strip()
        canonical_raw = body.get("canonical_model")
        canonical_model = str(canonical_raw).strip() if isinstance(canonical_raw, str) else None
        try:
            payload = self.state.requests.decide(
                request_ids=[str(i) for i in ids],
                action=action,
                auth=auth,
                canonical_model=canonical_model,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _hide_requests(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"ids"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        ids = body.get("ids")
        if not isinstance(ids, list):
            return json_result(400, {"error": "invalid_request", "message": "ids required"})
        try:
            payload = self.state.requests.hide(request_ids=[str(i) for i in ids], auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
