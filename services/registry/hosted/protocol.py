"""Hosted store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.hosted.rows import JobRow, SecretRow


@runtime_checkable
class HostedStoreProtocol(Protocol):
    def insert_secret(self, row: SecretRow) -> None: ...

    def get_secret(self, secret_id: str) -> SecretRow | None: ...

    def list_secrets(self, org_id: str) -> list[SecretRow]: ...

    def delete_secret(self, org_id: str, secret_id: str) -> bool: ...

    def insert_job(self, row: JobRow) -> None: ...

    def get_job(self, job_id: str) -> JobRow | None: ...

    def claim_next(self, *, worker_id: str) -> JobRow | None: ...

    def cancel_queued(self, job_id: str, *, finished_at: float) -> bool: ...

    def mark_cancel_requested(self, job_id: str) -> bool: ...

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        error_title: str,
        error_message: str,
        suite_run_id: str,
        finished_at: float,
    ) -> bool: ...

    def list_jobs(self, org_ids: list[str], dataset_id: str) -> list[JobRow]: ...

    def list_dataset_jobs(self, dataset_id: str) -> list[JobRow]: ...

    def requeue_stale(self, before: float) -> int: ...

    def cancel_stale(self, before: float, *, finished_at: float) -> int: ...
