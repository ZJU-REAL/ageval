"""Auth HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result


class AuthHandlers:
    def _auth_web_start(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.auth.web_start(
                redirect_uri=str(body.get("redirect_uri") or "").strip()
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _auth_web_callback(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.auth.web_callback(
                code=str(body.get("code") or "").strip(),
                state=str(body.get("state") or "").strip(),
                redirect_uri=str(body.get("redirect_uri") or "").strip(),
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _auth_device_code(self) -> HttpResult:
        try:
            return json_result(200, self.state.auth.device_code())
        except RegistryAppError as exc:
            return _caught(exc)

    def _auth_device_poll(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            status, payload = self.state.auth.device_poll(
                device_code=str(body.get("device_code") or "")
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(status, payload)

