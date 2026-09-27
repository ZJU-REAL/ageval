"""Runtime HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result


class RuntimeHandlers:
    def _detach_performance(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"suite_run_id", "role"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        try:
            payload = self.state.runtimes.detach_performance(
                package_id=dataset_id,
                suite_run_id=str(body.get("suite_run_id") or ""),
                role=str(body.get("role") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_performances(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        if qs:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(qs)),
                },
            )
        try:
            items = self.state.runtimes.list_performances(auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, {"items": items})

    def _patch_performance_collect(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"mode"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        mode = str(body.get("mode") or "").strip()
        try:
            payload = self.state.runtimes.set_collect_mode(
                package_id=dataset_id, mode=mode, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

