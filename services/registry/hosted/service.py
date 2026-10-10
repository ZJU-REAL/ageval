"""Hosted jobs and org secrets. Handlers call this; it does not touch blobs."""

from __future__ import annotations

import re
import secrets
from typing import Any

from services.registry.access import AccessPolicy
from services.registry.auth.tokens import TokenInfo
from services.registry.clock import now
from services.registry.errors import RegistryAppError
from services.registry.hosted import crypto
from services.registry.hosted.rows import (
    HOSTED_ENVIRONMENTS,
    PROVIDER_LOCATORS,
    RESERVED_MODEL_LOCATORS,
    SECRET_KINDS,
    TERMINAL_STATUSES,
    JobRow,
    SecretRow,
    job_to_dict,
    secret_to_dict,
)

from ageval.registry.media_types import DATASET_MEDIA_TYPE

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LOCATOR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MODEL_MAX = 200
_VALUE_MAX = 4096


class HostedService:
    """Membership-gated secrets and the e2b / daytona queue."""

    def __init__(self, hosted: Any, orgs: Any, packages: Any, access: AccessPolicy) -> None:
        self.hosted = hosted
        self.orgs = orgs
        self.packages = packages
        self.access = access

    def create_secret(
        self,
        *,
        org_id: str,
        name: str,
        kind: str,
        value: str,
        locator: str,
        provider: str,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        member = self._require_member(org_id, auth)
        secret_name = _name(name)
        if kind not in SECRET_KINDS:
            raise RegistryAppError(
                "invalid_request", "kind must be model or provider", http_status=400
            )
        _secret_value(value)
        stored_provider = ""
        if kind == "model":
            if provider:
                raise RegistryAppError(
                    "invalid_request",
                    "model secrets do not take a provider",
                    http_status=400,
                )
            stored_locator = _model_locator(locator)
        else:
            if provider not in PROVIDER_LOCATORS:
                raise RegistryAppError(
                    "invalid_request",
                    "provider must be e2b or daytona",
                    http_status=400,
                )
            stored_provider = provider
            fixed = PROVIDER_LOCATORS[provider]
            if locator and locator != fixed:
                raise RegistryAppError(
                    "invalid_request",
                    "provider locator is fixed by the environment",
                    http_status=400,
                )
            stored_locator = fixed
        row = SecretRow(
            secret_id=secrets.token_hex(8),
            org_id=member.org_id,
            name=secret_name,
            kind=kind,
            provider=stored_provider,
            locator=stored_locator,
            ciphertext=crypto.encrypt(value),
            created_by=auth.user_id or "",
            created_at=now(),
        )
        try:
            self.hosted.insert_secret(row)
        except ValueError as exc:
            raise RegistryAppError(
                "conflict",
                "secret name already exists",
                http_status=409,
            ) from exc
        return secret_to_dict(row)

    def list_secrets(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        self._require_member(org_id, auth)
        rows = self.hosted.list_secrets(org_id)
        return {"items": [secret_to_dict(row) for row in rows]}

    def delete_secret(self, *, org_id: str, secret_id: str, auth: TokenInfo) -> dict[str, Any]:
        member = self._require_member(org_id, auth)
        row = self.hosted.get_secret(secret_id)
        if row is None or row.org_id != org_id:
            raise RegistryAppError("not_found", "secret not found", http_status=404)
        allowed = (
            row.created_by == (auth.user_id or "")
            or member.role == "owner"
            or AccessPolicy.is_admin(auth.scopes)
        )
        if not allowed:
            raise RegistryAppError(
                "forbidden",
                "only the creator or an org owner can delete this secret",
                http_status=403,
            )
        self.hosted.delete_secret(org_id, secret_id)
        return {"ok": True, "secret_id": secret_id}

    def create_job(
        self,
        *,
        org_id: str,
        dataset_id: str,
        version: str,
        environment: str,
        model: str,
        model_secret_id: str,
        provider_secret_id: str,
        agent_ref: str,
        task_id: str,
        max_concurrent_tasks: Any,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        self._require_member(org_id, auth)
        if environment not in HOSTED_ENVIRONMENTS:
            raise RegistryAppError(
                "hosted_environment_refused",
                "hosted jobs accept only e2b or daytona",
                http_status=400,
            )
        dataset = _required_text(dataset_id, field="dataset_id", max_len=200)
        ver = _required_text(version, field="version", max_len=128)
        self._require_dataset(dataset, ver, auth)
        model_text = _model(model)
        agent = _optional_text(agent_ref, field="agent_ref", max_len=300)
        task = _optional_text(task_id, field="task_id", max_len=200)
        concurrency = _concurrency(max_concurrent_tasks)
        model_secret = self._org_secret(model_secret_id, org_id)
        provider_secret = self._org_secret(provider_secret_id, org_id)
        if model_secret.kind != "model":
            raise RegistryAppError(
                "invalid_request",
                "model_secret_id must be a model secret",
                http_status=400,
            )
        if provider_secret.kind != "provider" or provider_secret.provider != environment:
            raise RegistryAppError(
                "invalid_request",
                "provider secret does not match environment",
                http_status=400,
            )
        row = JobRow(
            job_id=secrets.token_hex(8),
            org_id=org_id,
            dataset_id=dataset,
            version=ver,
            environment=environment,
            agent_ref=agent,
            model=model_text,
            model_secret_id=model_secret.secret_id,
            provider_secret_id=provider_secret.secret_id,
            max_concurrent_tasks=concurrency,
            task_id=task,
            status="queued",
            error_title="",
            error_message="",
            suite_run_id="",
            created_by=auth.user_id or "",
            created_at=now(),
            started_at=None,
            finished_at=None,
            worker_id="",
            cancel_requested=False,
        )
        self.hosted.insert_job(row)
        return job_to_dict(row)

    def list_jobs(
        self,
        *,
        auth: TokenInfo,
        org_id: str,
        dataset_id: str,
    ) -> dict[str, Any]:
        if not org_id and not dataset_id:
            raise RegistryAppError(
                "invalid_request",
                "org_id or dataset_id required",
                http_status=400,
            )
        if org_id:
            self._require_member(org_id, auth)
            rows = self.hosted.list_jobs([org_id], dataset_id)
        elif AccessPolicy.is_admin(auth.scopes):
            rows = self.hosted.list_dataset_jobs(dataset_id)
        else:
            org_ids = sorted(self.orgs.user_org_ids(auth.user_id or ""))
            rows = self.hosted.list_jobs(org_ids, dataset_id)
        return {"items": [job_to_dict(row) for row in rows]}

    def get_job(self, *, job_id: str, auth: TokenInfo) -> dict[str, Any]:
        return job_to_dict(self._visible_job(job_id, auth))

    def cancel_job(self, *, job_id: str, auth: TokenInfo) -> dict[str, Any]:
        row = self._visible_job(job_id, auth)
        if row.status == "queued":
            if not self.hosted.cancel_queued(row.job_id, finished_at=now()):
                self.hosted.mark_cancel_requested(row.job_id)
        elif row.status == "running":
            self.hosted.mark_cancel_requested(row.job_id)
        elif row.status not in TERMINAL_STATUSES:
            raise RegistryAppError("invalid_request", "job cannot be canceled", http_status=400)
        fresh = self.hosted.get_job(job_id)
        return job_to_dict(fresh or row)

    def _require_member(self, org_id: str, auth: TokenInfo) -> Any:
        if not auth.user_id:
            raise RegistryAppError("not_found", "organization not found", http_status=404)
        member = self.orgs.membership(org_id, auth.user_id)
        if member is None:
            raise RegistryAppError("not_found", "organization not found", http_status=404)
        return member

    def _visible_job(self, job_id: str, auth: TokenInfo) -> JobRow:
        row = self.hosted.get_job(job_id)
        if row is None:
            raise RegistryAppError("not_found", "job not found", http_status=404)
        if AccessPolicy.is_admin(auth.scopes):
            return row
        if not auth.user_id or self.orgs.membership(row.org_id, auth.user_id) is None:
            raise RegistryAppError("not_found", "job not found", http_status=404)
        return row

    def _org_secret(self, secret_id: str, org_id: str) -> SecretRow:
        if not isinstance(secret_id, str) or not secret_id.strip():
            raise RegistryAppError("invalid_request", "secret id required", http_status=400)
        row = self.hosted.get_secret(secret_id.strip())
        if row is None or row.org_id != org_id:
            raise RegistryAppError("not_found", "secret not found", http_status=404)
        return row

    def _require_dataset(self, dataset_id: str, version: str, auth: TokenInfo) -> None:
        if version == "draft":
            draft = self.packages.get_draft(dataset_id)
            if draft is None or not self.access.entitled_to_draft(draft, auth):
                raise RegistryAppError("not_found", "dataset not found", http_status=404)
            if draft.package_kind != "dataset":
                raise RegistryAppError(
                    "invalid_request",
                    "package is not a dataset",
                    http_status=400,
                )
            return
        row = self.packages.get_by_version(dataset_id, version)
        if row is None or not self.access.visible_package(row, auth):
            raise RegistryAppError("not_found", "dataset not found", http_status=404)
        if row.media_type != DATASET_MEDIA_TYPE:
            raise RegistryAppError("invalid_request", "package is not a dataset", http_status=400)


def _name(raw: Any) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "name must be a string", http_status=400)
    text = raw.strip()
    if not _NAME_RE.fullmatch(text):
        raise RegistryAppError("invalid_request", "bad secret name", http_status=400)
    return text


def _secret_value(raw: Any) -> str:
    if not isinstance(raw, str) or raw == "" or raw.strip() == "":
        raise RegistryAppError("invalid_request", "value required", http_status=400)
    if len(raw) > _VALUE_MAX or "\n" in raw or "\r" in raw:
        raise RegistryAppError("invalid_request", "bad secret value", http_status=400)
    return raw


def _model_locator(raw: Any) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "locator required", http_status=400)
    text = raw.strip()
    if not _LOCATOR_RE.fullmatch(text):
        raise RegistryAppError("invalid_request", "bad model locator", http_status=400)
    if text in RESERVED_MODEL_LOCATORS:
        raise RegistryAppError(
            "invalid_request",
            "model locator must not be a sandbox provider key",
            http_status=400,
        )
    return text


def _model(raw: Any) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "model required", http_status=400)
    if "\n" in raw or "\r" in raw or len(raw) > _MODEL_MAX:
        raise RegistryAppError("invalid_request", "bad model", http_status=400)
    text = raw.strip()
    if not text:
        raise RegistryAppError("invalid_request", "model required", http_status=400)
    return text


def _required_text(raw: Any, *, field: str, max_len: int) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", f"{field} required", http_status=400)
    if "\n" in raw or "\r" in raw or len(raw) > max_len:
        raise RegistryAppError("invalid_request", f"bad {field}", http_status=400)
    text = raw.strip()
    if not text:
        raise RegistryAppError("invalid_request", f"{field} required", http_status=400)
    return text


def _optional_text(raw: Any, *, field: str, max_len: int) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", f"{field} must be a string", http_status=400)
    if "\n" in raw or "\r" in raw or len(raw) > max_len:
        raise RegistryAppError("invalid_request", f"bad {field}", http_status=400)
    return raw.strip()


def _concurrency(raw: Any) -> int:
    if raw is None:
        return 1
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RegistryAppError(
            "invalid_request",
            "max_concurrent_tasks must be an integer",
            http_status=400,
        )
    if raw < 1 or raw > 32:
        raise RegistryAppError(
            "invalid_request",
            "max_concurrent_tasks must be from 1 to 32",
            http_status=400,
        )
    return raw
