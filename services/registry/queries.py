"""Shared SQL text for Registry metadata stores (SQLite ``?`` placeholders).

Postgres adapters rewrite placeholders in :mod:`services.registry.db.sql_adapter`.
DDL lives here once; dialect adapters only connect / placeholder / row-map.
"""

from __future__ import annotations

from typing import Any

# ---- releases --------------------------------------------------------------




# ---- attempt / suite results -----------------------------------------------

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

# ---- orgs ------------------------------------------------------------------



# Types chosen so SQLite and Postgres accept the same CREATE TABLE text.
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
    """
    CREATE TABLE IF NOT EXISTS snapshot_shares (
        token TEXT PRIMARY KEY,
        owner_user_id TEXT NOT NULL,
        suite_run_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        summary_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        run_id TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshot_shares_blob
    ON snapshot_shares(blob_digest)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        token_hash TEXT PRIMARY KEY,
        scopes TEXT NOT NULL,
        github_user TEXT,
        created_at REAL NOT NULL DEFAULT 0,
        revoked_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suite_agent_consents (
        suite_run_id TEXT NOT NULL,
        package_id TEXT NOT NULL,
        granted_by TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (suite_run_id, package_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suite_canonical_models (
        suite_run_id TEXT NOT NULL,
        overlay_model TEXT NOT NULL,
        canonical_model TEXT NOT NULL,
        PRIMARY KEY (suite_run_id, overlay_model)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_requests (
        request_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        suite_run_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        applicant TEXT NOT NULL,
        owner_org_id TEXT NOT NULL,
        agent_ref TEXT NOT NULL DEFAULT '',
        canonical_model TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        decided_at REAL,
        decided_by TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_requests_inbox
    ON resource_requests(owner_org_id, status, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_performance_collect (
        package_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inbox_hidden (
        user_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        hidden_at REAL NOT NULL,
        PRIMARY KEY (user_id, request_id)
    )
    """,
)

# ---- dataset draft / ACL ---------------------------------------------------

DELETE_DATASET_ACL = "DELETE FROM dataset_acl WHERE dataset_id=? AND user_id=?"

# Live Postgres may have created these as BOOLEAN; inserts bind 0/1 (INTEGER).
SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = (
    ("suite_results", "board_listed"),
)

# (table, column, sqlite/postgres-compatible type clause)
SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("suite_results", "config_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("attempt_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "suite_run_id", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "environment", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "agent_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "model_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "score", "REAL"),
    # API names are error and limit. `limit` is reserved in Postgres.
    ("attempt_results", "error_json", "TEXT"),
    ("attempt_results", "limit_name", "TEXT"),
    ("attempt_results", "dataset_version", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "complete", "INTEGER NOT NULL DEFAULT 0"),
    ("suite_results", "bound_kind", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("suite_results", "task_set_digest", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "board_listed", "INTEGER NOT NULL DEFAULT 0"),
    ("resource_requests", "canonical_model", "TEXT NOT NULL DEFAULT ''"),
    ("snapshot_shares", "run_id", "TEXT NOT NULL DEFAULT ''"),
)

# Do not bind created_at. Pre-unification Postgres token tables are
# TIMESTAMPTZ DEFAULT now(); an epoch float fails to insert. New tables
# use REAL DEFAULT 0. Token created_at is never read.
UPSERT_TOKEN = """
INSERT INTO api_tokens(token_hash, scopes, github_user)
VALUES (?, ?, ?)
ON CONFLICT(token_hash) DO UPDATE SET
    scopes=excluded.scopes,
    github_user=excluded.github_user,
    revoked_at=NULL
"""

SELECT_TOKEN = "SELECT scopes, github_user, revoked_at FROM api_tokens WHERE token_hash=?"

# ---- remaining store SQL ---------------------------------------------------

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
UPSERT_SUITE_AGENT_CONSENT = """
INSERT INTO suite_agent_consents(
    suite_run_id, package_id, granted_by, source, created_at
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(suite_run_id, package_id) DO NOTHING
"""
SELECT_SUITE_AGENT_CONSENT = (
    "SELECT * FROM suite_agent_consents WHERE suite_run_id=? AND package_id=?"
)
LIST_SUITE_AGENT_CONSENTS = "SELECT * FROM suite_agent_consents WHERE suite_run_id=?"
LIST_AGENT_CONSENTS_FOR_SUITES = (
    "SELECT * FROM suite_agent_consents WHERE suite_run_id IN ({placeholders})"
)
UPDATE_SUITE_BOARD_LISTED = "UPDATE suite_results SET board_listed=? WHERE suite_run_id=?"
UPSERT_SUITE_CANONICAL_MODEL = """
INSERT INTO suite_canonical_models(suite_run_id, overlay_model, canonical_model)
VALUES (?, ?, ?)
ON CONFLICT(suite_run_id, overlay_model) DO UPDATE SET
    canonical_model=excluded.canonical_model
"""
LIST_CANONICAL_MODELS_FOR_SUITES = (
    "SELECT * FROM suite_canonical_models WHERE suite_run_id IN ({placeholders})"
)
INSERT_RESOURCE_REQUEST = """
INSERT INTO resource_requests(
    request_id, kind, status, suite_run_id, dataset_id, applicant,
    owner_org_id, agent_ref, canonical_model, created_at, decided_at, decided_by
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
SELECT_RESOURCE_REQUEST = "SELECT * FROM resource_requests WHERE request_id=?"
LIST_RESOURCE_REQUESTS_BY_IDS = (
    "SELECT * FROM resource_requests WHERE request_id IN ({placeholders})"
)
LIST_INBOX_REQUESTS = "SELECT * FROM resource_requests WHERE owner_org_id IN ({placeholders})"
LIST_SUITE_REQUESTS = (
    "SELECT * FROM resource_requests WHERE suite_run_id=? ORDER BY created_at DESC"
)
SELECT_PENDING_REQUEST = """
SELECT * FROM resource_requests
WHERE kind=? AND suite_run_id=? AND status='pending' AND agent_ref=?
"""
UPDATE_RESOURCE_REQUEST_STATUS = """
UPDATE resource_requests SET status=?, decided_at=?, decided_by=?
WHERE request_id=? AND status='pending'
"""
SELECT_PERFORMANCE_COLLECT = "SELECT mode FROM agent_performance_collect WHERE package_id=?"
LIST_PERFORMANCE_COLLECT = "SELECT package_id, mode FROM agent_performance_collect"
UPSERT_PERFORMANCE_COLLECT = """
INSERT INTO agent_performance_collect(package_id, mode, updated_by, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(package_id) DO UPDATE SET
    mode=excluded.mode,
    updated_by=excluded.updated_by,
    updated_at=excluded.updated_at
"""
UPSERT_INBOX_HIDDEN = """
INSERT INTO inbox_hidden(user_id, request_id, hidden_at)
VALUES (?, ?, ?)
ON CONFLICT(user_id, request_id) DO UPDATE SET
    hidden_at=excluded.hidden_at
"""
LIST_INBOX_HIDDEN_FOR_USER = "SELECT request_id FROM inbox_hidden WHERE user_id=?"
DELETE_SUITE_PACKAGE_CONSENT = (
    "DELETE FROM suite_agent_consents WHERE suite_run_id=? AND package_id=?"
)
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
INSERT_SNAPSHOT_SHARE = """
INSERT INTO snapshot_shares(
    token, owner_user_id, suite_run_id, dataset_id, dataset_version,
    blob_digest, size, summary_json, created_at, run_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
SELECT_SNAPSHOT_SHARE = "SELECT * FROM snapshot_shares WHERE token=?"
SELECT_SNAPSHOT_SHARE_FOR_OWNER = """
SELECT * FROM snapshot_shares
WHERE owner_user_id=? AND suite_run_id=? AND run_id=?
ORDER BY created_at DESC
LIMIT 1
"""
DELETE_SNAPSHOT_SHARE = "DELETE FROM snapshot_shares WHERE token=?"
COUNT_SNAPSHOT_SHARE_BLOB = "SELECT COUNT(*) AS n FROM snapshot_shares WHERE blob_digest=?"
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
