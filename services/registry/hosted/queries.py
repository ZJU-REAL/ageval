"""Hosted secret and job SQL."""

from __future__ import annotations

from typing import Any

INSERT_SECRET = """
INSERT INTO hosted_secrets(
    secret_id, org_id, name, kind, provider, locator, ciphertext, created_by, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_SECRET = "SELECT * FROM hosted_secrets WHERE secret_id=?"

LIST_SECRETS = "SELECT * FROM hosted_secrets WHERE org_id=? ORDER BY created_at"

DELETE_SECRET = "DELETE FROM hosted_secrets WHERE secret_id=? AND org_id=?"

INSERT_JOB = """
INSERT INTO hosted_jobs(
    job_id, org_id, dataset_id, version, environment, agent_ref, model,
    model_secret_id, provider_secret_id, max_concurrent_tasks, task_id,
    status, error_title, error_message, suite_run_id, created_by, created_at,
    started_at, finished_at, worker_id, cancel_requested
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_JOB = "SELECT * FROM hosted_jobs WHERE job_id=?"

CLAIM_NEXT = """
UPDATE hosted_jobs
SET status='running', started_at=?, worker_id=?
WHERE job_id=(
    SELECT job_id FROM hosted_jobs
    WHERE status='queued'
    ORDER BY created_at
    LIMIT 1
) AND status='queued'
"""

SELECT_CLAIMED = """
SELECT * FROM hosted_jobs
WHERE worker_id=? AND status='running'
ORDER BY started_at DESC
"""

CANCEL_QUEUED = """
UPDATE hosted_jobs
SET status='canceled', finished_at=?, error_title='', error_message=''
WHERE job_id=? AND status='queued'
"""

MARK_CANCEL_REQUESTED = """
UPDATE hosted_jobs SET cancel_requested=1
WHERE job_id=? AND status='running'
"""

FINISH_JOB = """
UPDATE hosted_jobs
SET status=?, error_title=?, error_message=?, suite_run_id=?, finished_at=?
WHERE job_id=? AND status='running'
"""

REQUEUE_STALE = """
UPDATE hosted_jobs
SET status='queued', worker_id='', started_at=NULL
WHERE status='running' AND cancel_requested=0 AND started_at IS NOT NULL AND started_at < ?
"""

CANCEL_STALE = """
UPDATE hosted_jobs
SET status='canceled', finished_at=?, worker_id=''
WHERE status='running' AND cancel_requested=1 AND started_at IS NOT NULL AND started_at < ?
"""


def list_jobs_query(*, org_ids: list[str], dataset_id: str) -> tuple[str, list[Any]]:
    """Jobs visible to the given orgs, optionally one dataset."""
    if not org_ids:
        return "SELECT * FROM hosted_jobs WHERE 1=0", []
    marks = ",".join("?" for _ in org_ids)
    sql = f"SELECT * FROM hosted_jobs WHERE org_id IN ({marks})"
    params: list[Any] = list(org_ids)
    if dataset_id:
        sql += " AND dataset_id=?"
        params.append(dataset_id)
    sql += " ORDER BY created_at DESC"
    return sql, params


def list_dataset_jobs_query(dataset_id: str) -> tuple[str, list[Any]]:
    return (
        "SELECT * FROM hosted_jobs WHERE dataset_id=? ORDER BY created_at DESC",
        [dataset_id],
    )


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS hosted_secrets (
        secret_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT '',
        locator TEXT NOT NULL,
        ciphertext TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE (org_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hosted_jobs (
        job_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        version TEXT NOT NULL,
        environment TEXT NOT NULL,
        agent_ref TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        model_secret_id TEXT NOT NULL,
        provider_secret_id TEXT NOT NULL,
        max_concurrent_tasks INTEGER NOT NULL,
        task_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        error_title TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        suite_run_id TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        started_at REAL,
        finished_at REAL,
        worker_id TEXT NOT NULL DEFAULT '',
        cancel_requested INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hosted_jobs_status_created
    ON hosted_jobs(status, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hosted_jobs_dataset
    ON hosted_jobs(dataset_id, created_at)
    """,
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = ()
