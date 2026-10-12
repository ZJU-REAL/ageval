"""Hosted job and org secret HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result

_SECRET_KEYS = {"name", "kind", "value", "locator", "provider"}
_JOB_KEYS = {
    "org_id",
    "dataset_id",
    "version",
    "environment",
    "model",
    "model_secret_id",
    "provider_secret_id",
    "agent_ref",
    "task_id",
    "max_concurrent_tasks",
}
_LIST_KEYS = {"org_id", "dataset_id"}


class HostedHandlers:
    def _create_org_secret(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        if _unknown(body, _SECRET_KEYS):
            return _unknown_result()
        try:
            payload = self.state.hosted.create_secret(
                org_id=org_id,
                name=body.get("name"),
                kind=str(body.get("kind") or ""),
                value=body.get("value"),
                locator=str(body.get("locator") or ""),
                provider=str(body.get("provider") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _list_org_secrets(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.hosted.list_secrets(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_org_secret(self, *, org_id: str, secret_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.hosted.delete_secret(org_id=org_id, secret_id=secret_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _create_hosted_job(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        if _unknown(body, _JOB_KEYS):
            return _unknown_result()
        try:
            payload = self.state.hosted.create_job(
                org_id=str(body.get("org_id") or ""),
                dataset_id=body.get("dataset_id"),
                version=body.get("version"),
                environment=str(body.get("environment") or ""),
                model=body.get("model"),
                model_secret_id=str(body.get("model_secret_id") or ""),
                provider_secret_id=str(body.get("provider_secret_id") or ""),
                agent_ref=body.get("agent_ref"),
                task_id=body.get("task_id"),
                max_concurrent_tasks=body.get("max_concurrent_tasks"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _list_hosted_jobs(self, *, auth: TokenInfo, qs: Mapping[str, list[str]]) -> HttpResult:
        if _unknown(qs, _LIST_KEYS):
            return _unknown_result()
        try:
            payload = self.state.hosted.list_jobs(
                auth=auth,
                org_id=_qs_one(qs, "org_id"),
                dataset_id=_qs_one(qs, "dataset_id"),
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _get_hosted_job(self, *, job_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.hosted.get_job(job_id=job_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _cancel_hosted_job(self, *, job_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.hosted.cancel_job(job_id=job_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)


def _unknown(body: Mapping[str, Any], allowed: set[str]) -> bool:
    return any(key not in allowed for key in body)


def _unknown_result() -> HttpResult:
    return json_result(400, {"error": "invalid_request", "message": "unknown keys"})


def _qs_one(qs: Mapping[str, list[str]], key: str) -> str:
    raw = qs.get(key) or []
    if not raw:
        return ""
    return str(raw[0] or "")
