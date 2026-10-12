"""Hosted aggregate: org secrets and the job queue."""

from __future__ import annotations

from typing import Any

from services.registry.hosted import queries as Q
from services.registry.hosted.protocol import HostedStoreProtocol
from services.registry.hosted.rows import JobRow, SecretRow


class HostedStore(HostedStoreProtocol):
    """Org secrets and hosted jobs. SQL lives in ``queries``."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def insert_secret(self, row: SecretRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_SECRET,
                    (
                        row.secret_id,
                        row.org_id,
                        row.name,
                        row.kind,
                        row.provider,
                        row.locator,
                        row.ciphertext,
                        row.created_by,
                        row.created_at,
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("secret name already exists") from exc

    def get_secret(self, secret_id: str) -> SecretRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SECRET, (secret_id,))
            found = cur.fetchone()
            return _secret_row(found) if found else None

    def list_secrets(self, org_id: str) -> list[SecretRow]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_SECRETS, (org_id,))
            return [_secret_row(row) for row in cur.fetchall()]

    def delete_secret(self, org_id: str, secret_id: str) -> bool:
        with self._connect() as conn:
            cur = self._exec(conn, Q.DELETE_SECRET, (secret_id, org_id))
            conn.commit()
            changed = cur.rowcount
        if changed > 0:
            return True
        if changed == 0:
            return False
        return self.get_secret(secret_id) is None

    def insert_job(self, row: JobRow) -> None:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.INSERT_JOB,
                (
                    row.job_id,
                    row.org_id,
                    row.dataset_id,
                    row.version,
                    row.environment,
                    row.agent_ref,
                    row.model,
                    row.model_secret_id,
                    row.provider_secret_id,
                    row.max_concurrent_tasks,
                    row.task_id,
                    row.status,
                    row.error_title,
                    row.error_message,
                    row.suite_run_id,
                    row.created_by,
                    row.created_at,
                    row.started_at,
                    row.finished_at,
                    row.worker_id,
                    1 if row.cancel_requested else 0,
                ),
            )
            conn.commit()

    def get_job(self, job_id: str) -> JobRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_JOB, (job_id,))
            found = cur.fetchone()
            return _job_row(found) if found else None

    def claim_next(self, *, worker_id: str) -> JobRow | None:
        from services.registry.clock import now

        started = now()
        with self._connect() as conn:
            cur = self._exec(conn, Q.CLAIM_NEXT, (started, worker_id))
            conn.commit()
            changed = cur.rowcount
        if changed == 0:
            return None
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_CLAIMED, (worker_id,))
            found = cur.fetchone()
            return _job_row(found) if found else None

    def cancel_queued(self, job_id: str, *, finished_at: float) -> bool:
        with self._connect() as conn:
            cur = self._exec(conn, Q.CANCEL_QUEUED, (finished_at, job_id))
            conn.commit()
            changed = cur.rowcount
        if changed > 0:
            return True
        if changed == 0:
            return False
        row = self.get_job(job_id)
        return row is not None and row.status == "canceled"

    def mark_cancel_requested(self, job_id: str) -> bool:
        with self._connect() as conn:
            cur = self._exec(conn, Q.MARK_CANCEL_REQUESTED, (job_id,))
            conn.commit()
            changed = cur.rowcount
        if changed > 0:
            return True
        if changed == 0:
            return False
        row = self.get_job(job_id)
        return row is not None and row.cancel_requested

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        error_title: str,
        error_message: str,
        suite_run_id: str,
        finished_at: float,
    ) -> bool:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.FINISH_JOB,
                (status, error_title, error_message, suite_run_id, finished_at, job_id),
            )
            conn.commit()
            changed = cur.rowcount
        if changed > 0:
            return True
        if changed == 0:
            return False
        row = self.get_job(job_id)
        return row is not None and row.status == status

    def list_jobs(self, org_ids: list[str], dataset_id: str) -> list[JobRow]:
        sql, params = Q.list_jobs_query(org_ids=list(org_ids), dataset_id=dataset_id)
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(params))
            return [_job_row(row) for row in cur.fetchall()]

    def list_dataset_jobs(self, dataset_id: str) -> list[JobRow]:
        sql, params = Q.list_dataset_jobs_query(dataset_id)
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(params))
            return [_job_row(row) for row in cur.fetchall()]

    def requeue_stale(self, before: float) -> int:
        with self._connect() as conn:
            cur = self._exec(conn, Q.REQUEUE_STALE, (before,))
            conn.commit()
            return changed_rows(cur.rowcount)

    def cancel_stale(self, before: float, *, finished_at: float) -> int:
        with self._connect() as conn:
            cur = self._exec(conn, Q.CANCEL_STALE, (finished_at, before))
            conn.commit()
            return changed_rows(cur.rowcount)


def changed_rows(rowcount: int) -> int:
    return rowcount if rowcount > 0 else 0


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return int(value or 0) != 0


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _secret_row(record: Any) -> SecretRow:
    return SecretRow(
        secret_id=str(record["secret_id"]),
        org_id=str(record["org_id"]),
        name=str(record["name"]),
        kind=str(record["kind"]),
        provider=str(record["provider"] or ""),
        locator=str(record["locator"]),
        ciphertext=str(record["ciphertext"]),
        created_by=str(record["created_by"]),
        created_at=float(record["created_at"]),
    )


def _job_row(record: Any) -> JobRow:
    return JobRow(
        job_id=str(record["job_id"]),
        org_id=str(record["org_id"]),
        dataset_id=str(record["dataset_id"]),
        version=str(record["version"]),
        environment=str(record["environment"]),
        agent_ref=str(record["agent_ref"] or ""),
        model=str(record["model"]),
        model_secret_id=str(record["model_secret_id"]),
        provider_secret_id=str(record["provider_secret_id"]),
        max_concurrent_tasks=int(record["max_concurrent_tasks"]),
        task_id=str(record["task_id"] or ""),
        status=str(record["status"]),
        error_title=str(record["error_title"] or ""),
        error_message=str(record["error_message"] or ""),
        suite_run_id=str(record["suite_run_id"] or ""),
        created_by=str(record["created_by"]),
        created_at=float(record["created_at"]),
        started_at=_optional_float(record["started_at"]),
        finished_at=_optional_float(record["finished_at"]),
        worker_id=str(record["worker_id"] or ""),
        cancel_requested=_flag(record["cancel_requested"]),
    )
