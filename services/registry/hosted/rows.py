"""Hosted secret and job rows. Public dicts never include ciphertext."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HOSTED_ENVIRONMENTS = frozenset({"e2b", "daytona"})
SECRET_KINDS = frozenset({"model", "provider"})
PROVIDER_LOCATORS = {
    "e2b": "E2B_API_KEY",
    "daytona": "DAYTONA_API_KEY",
}
# Model locators must not be the sandbox-provider names. Those stay on the worker.
RESERVED_MODEL_LOCATORS = frozenset(
    {
        "E2B_API_KEY",
        "e2b_api_key",
        "DAYTONA_API_KEY",
        "daytona_api_key",
    }
)
JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "canceled"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})


@dataclass(frozen=True, slots=True)
class SecretRow:
    secret_id: str
    org_id: str
    name: str
    kind: str
    provider: str
    locator: str
    ciphertext: str
    created_by: str
    created_at: float


@dataclass(frozen=True, slots=True)
class JobRow:
    job_id: str
    org_id: str
    dataset_id: str
    version: str
    environment: str
    agent_ref: str
    model: str
    model_secret_id: str
    provider_secret_id: str
    max_concurrent_tasks: int
    task_id: str
    status: str
    error_title: str
    error_message: str
    suite_run_id: str
    created_by: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    worker_id: str
    cancel_requested: bool


def secret_to_dict(row: SecretRow) -> dict[str, Any]:
    """Metadata only. ``ciphertext`` stays on the row object."""
    out: dict[str, Any] = {
        "secret_id": row.secret_id,
        "org_id": row.org_id,
        "name": row.name,
        "kind": row.kind,
        "locator": row.locator,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if row.provider:
        out["provider"] = row.provider
    return out


def job_to_dict(row: JobRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "job_id": row.job_id,
        "org_id": row.org_id,
        "dataset_id": row.dataset_id,
        "version": row.version,
        "environment": row.environment,
        "model": row.model,
        "model_secret_id": row.model_secret_id,
        "provider_secret_id": row.provider_secret_id,
        "max_concurrent_tasks": row.max_concurrent_tasks,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "cancel_requested": row.cancel_requested,
    }
    if row.agent_ref:
        out["agent_ref"] = row.agent_ref
    if row.task_id:
        out["task_id"] = row.task_id
    if row.error_title:
        out["error"] = {"title": row.error_title, "message": row.error_message}
    if row.suite_run_id:
        out["suite_run_id"] = row.suite_run_id
    if row.started_at is not None:
        out["started_at"] = row.started_at
    if row.finished_at is not None:
        out["finished_at"] = row.finished_at
    return out
