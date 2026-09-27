"""Attempt, suite, and result-share SQL."""

from __future__ import annotations

from typing import Any

INSERT_ATTEMPT = """
INSERT INTO attempt_results(
    run_id, dataset_id, dataset_version, task_id, lock_digest, status,
    visibility, blob_digest, size, created_at, uploaded_by,
    suite_run_id, environment, agent_label, model_label, score,
    error_json, limit_name
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_ATTEMPT = "SELECT * FROM attempt_results WHERE run_id=?"

INSERT_SUITE = """
INSERT INTO suite_results(
    suite_run_id, dataset_id, dataset_version, visibility,
    pass_rate, mean_score, metrics_json, tasks_json,
    agent_label, model_label, blob_digest, size,
    exit_code, created_at, config_json, uploaded_by,
    complete, bound_kind, task_set_digest
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_SUITE = "SELECT * FROM suite_results WHERE suite_run_id=?"

DELETE_ATTEMPT_SHARES = "DELETE FROM result_shares WHERE result_kind='attempt' AND result_id=?"

DELETE_ATTEMPT = "DELETE FROM attempt_results WHERE run_id=?"

UPDATE_ATTEMPT_VISIBILITY = "UPDATE attempt_results SET visibility=? WHERE run_id=?"

DELETE_SUITE_SHARES = "DELETE FROM result_shares WHERE result_kind='suite' AND result_id=?"

DELETE_SUITE_CONSENTS = "DELETE FROM suite_agent_consents WHERE suite_run_id=?"

DELETE_SUITE_REQUESTS = "DELETE FROM resource_requests WHERE suite_run_id=?"

DELETE_SUITE = "DELETE FROM suite_results WHERE suite_run_id=?"

UPDATE_SUITE_VISIBILITY = "UPDATE suite_results SET visibility=? WHERE suite_run_id=?"

UPDATE_SUITE_SLOT = """
UPDATE suite_results SET
    pass_rate=?, mean_score=?, metrics_json=?, tasks_json=?,
    exit_code=?, complete=?
WHERE suite_run_id=?
"""

UPDATE_SUITE_CONFIG_JSON = "UPDATE suite_results SET config_json=? WHERE suite_run_id=?"

UPDATE_SUITE_BOARD_LISTED = "UPDATE suite_results SET board_listed=? WHERE suite_run_id=?"

SELECT_ATTEMPTS_FOR_SUITE = (
    "SELECT * FROM attempt_results WHERE suite_run_id=? ORDER BY created_at DESC"
)

COUNT_ATTEMPT_BLOB_REFS = "SELECT COUNT(*) AS n FROM attempt_results WHERE blob_digest=?"

COUNT_SUITE_BLOB_REFS = "SELECT COUNT(*) AS n FROM suite_results WHERE blob_digest=?"

INSERT_RESULT_SHARE = """
INSERT INTO result_shares(
    result_kind, result_id, target_type, target_id, created_at
) VALUES (?, ?, ?, ?, ?)
"""

DELETE_RESULT_SHARE = """
DELETE FROM result_shares
WHERE result_kind=? AND result_id=? AND target_type=? AND target_id=?
"""

SELECT_RESULT_SHARES = """
SELECT * FROM result_shares
WHERE result_kind=? AND result_id=?
ORDER BY target_type, target_id
"""

SELECT_RESULT_SHARED_USER = """
SELECT 1 FROM result_shares
WHERE result_kind=? AND result_id=? AND target_type='user' AND target_id=?
LIMIT 1
"""

def list_attempts_query(
    *,
    dataset_id: str | None = None,
    task_id: str | None = None,
    standalone: bool = False,
    include_private: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_private:
        clauses.append("visibility = 'public'")
    if dataset_id:
        clauses.append("dataset_id = ?")
        params.append(dataset_id)
    if task_id:
        clauses.append("task_id = ?")
        params.append(task_id)
    if standalone:
        clauses.append("(suite_run_id IS NULL OR suite_run_id = '')")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return f"SELECT * FROM attempt_results {where} ORDER BY created_at DESC", params

def list_suites_query(
    *,
    dataset_id: str | None = None,
    include_private: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_private:
        clauses.append("visibility = 'public'")
    if dataset_id:
        clauses.append("dataset_id = ?")
        params.append(dataset_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return f"SELECT * FROM suite_results {where} ORDER BY created_at DESC", params

def select_attempts_in_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return f"SELECT * FROM attempt_results WHERE run_id IN ({placeholders})"

def select_result_shared_orgs_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return f"""
                SELECT 1 FROM result_shares
                WHERE result_kind=? AND result_id=? AND target_type='org'
                  AND target_id IN ({placeholders})
                LIMIT 1
                """

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS attempt_results (
        run_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        lock_digest TEXT NOT NULL,
        status TEXT NOT NULL,
        visibility TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suite_results (
        suite_run_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        visibility TEXT NOT NULL,
        pass_rate REAL NOT NULL,
        mean_score REAL NOT NULL,
        metrics_json TEXT NOT NULL,
        tasks_json TEXT NOT NULL,
        agent_label TEXT NOT NULL DEFAULT '',
        model_label TEXT NOT NULL DEFAULT '',
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        exit_code INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        config_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_shares (
        result_kind TEXT NOT NULL,
        result_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (result_kind, result_id, target_type, target_id)
    )
    """,
)

SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = (
    ("suite_results", "board_listed"),
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("suite_results", "config_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("attempt_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "suite_run_id", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "environment", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "agent_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "model_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "score", "REAL"),
    ("attempt_results", "error_json", "TEXT"),
    ("attempt_results", "limit_name", "TEXT"),
    ("attempt_results", "dataset_version", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "complete", "INTEGER NOT NULL DEFAULT 0"),
    ("suite_results", "bound_kind", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("suite_results", "task_set_digest", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "board_listed", "INTEGER NOT NULL DEFAULT 0"),
)
