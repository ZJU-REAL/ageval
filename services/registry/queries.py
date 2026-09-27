"""Shared SQL text for Registry metadata stores (SQLite ``?`` placeholders).

Postgres adapters rewrite placeholders in :mod:`services.registry.db.sql_adapter`.
DDL lives here once; dialect adapters only connect / placeholder / row-map.
"""

from __future__ import annotations

from typing import Any

# ---- releases --------------------------------------------------------------




# ---- attempt / suite results -----------------------------------------------

# ---- orgs ------------------------------------------------------------------



# Types chosen so SQLite and Postgres accept the same CREATE TABLE text.
SCHEMA_STATEMENTS: tuple[str, ...] = (
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
)

# (table, column, sqlite/postgres-compatible type clause)
SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # API names are error and limit. `limit` is reserved in Postgres.
    ("resource_requests", "canonical_model", "TEXT NOT NULL DEFAULT ''"),
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
