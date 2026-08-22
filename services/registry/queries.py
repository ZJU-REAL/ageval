"""Shared SQL text for Registry metadata stores (SQLite ``?`` placeholders).

Postgres adapters rewrite placeholders in :mod:`services.registry.sql_adapter`.
DDL lives here once; dialect adapters only connect / placeholder / row-map.
"""

from __future__ import annotations

from typing import Any

# ---- releases --------------------------------------------------------------

INSERT_RELEASE = """
INSERT INTO releases(
    dataset_id, version, visibility, package_digest,
    blob_digest, size, media_type, created_at, org_id, uploaded_by
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_RELEASE_BY_VERSION = "SELECT * FROM releases WHERE dataset_id=? AND version=?"

SELECT_RELEASE_BY_DIGEST = "SELECT * FROM releases WHERE dataset_id=? AND package_digest=?"


def list_releases_query(
    *,
    dataset_id_prefix: str | None = None,
    visibility: str | None = None,
    version: str | None = None,
    include_private: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_private:
        clauses.append("visibility = 'public'")
    elif visibility in {"public", "private"}:
        clauses.append("visibility = ?")
        params.append(visibility)
    if dataset_id_prefix:
        clauses.append("dataset_id LIKE ?")
        params.append(f"{dataset_id_prefix}%")
    if version:
        clauses.append("version = ?")
        params.append(version)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM releases {where} ORDER BY dataset_id, version"
    return sql, params


def list_versions_query(dataset_id: str, *, include_private: bool = False) -> tuple[str, list[Any]]:
    clauses = ["dataset_id = ?"]
    params: list[Any] = [dataset_id]
    if not include_private:
        clauses.append("visibility = 'public'")
    where = " AND ".join(clauses)
    return f"SELECT * FROM releases WHERE {where} ORDER BY version", params


# ---- attempt / suite results -----------------------------------------------

INSERT_ATTEMPT = """
INSERT INTO attempt_results(
    run_id, dataset_id, task_id, lock_digest, status,
    visibility, blob_digest, size, created_at, uploaded_by,
    suite_run_id, environment, agent_label, model_label, score
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

INSERT_ORG = """
INSERT INTO organizations(
    org_id, name, display_name, description, is_claimable, created_at
) VALUES (?, ?, ?, ?, ?, ?)
"""

INSERT_ORG_OWNER_MEMBERSHIP = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'owner', ?)
"""

SELECT_ORG = "SELECT * FROM organizations WHERE org_id=?"

UPDATE_ORG_DISPLAY_NAME = "UPDATE organizations SET display_name=? WHERE org_id=?"
UPDATE_ORG_DESCRIPTION = "UPDATE organizations SET description=? WHERE org_id=?"
UPDATE_ORG_DISPLAY_AND_DESCRIPTION = (
    "UPDATE organizations SET display_name=?, description=? WHERE org_id=?"
)

UPSERT_PACKAGE_DISPLAY_NAME = """
INSERT INTO package_display_names(dataset_id, display_name, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(dataset_id) DO UPDATE SET
    display_name=excluded.display_name,
    updated_at=excluded.updated_at
"""

SELECT_PACKAGE_DISPLAY_NAME = "SELECT display_name FROM package_display_names WHERE dataset_id=?"

SELECT_PACKAGE_DISPLAY_NAMES = "SELECT dataset_id, display_name FROM package_display_names"

UPSERT_PACKAGE_ICON = """
INSERT INTO package_icons(dataset_id, icon_key, icon_github, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(dataset_id) DO UPDATE SET
    icon_key=excluded.icon_key,
    icon_github=excluded.icon_github,
    updated_at=excluded.updated_at
"""

DELETE_PACKAGE_ICON = "DELETE FROM package_icons WHERE dataset_id=?"

SELECT_PACKAGE_ICON = "SELECT icon_key, icon_github FROM package_icons WHERE dataset_id=?"

SELECT_PACKAGE_ICONS = "SELECT dataset_id, icon_key, icon_github FROM package_icons"

SELECT_MEMBERSHIP = "SELECT * FROM org_memberships WHERE org_id=? AND user_id=?"

SELECT_USER_ORG_IDS = "SELECT org_id FROM org_memberships WHERE user_id=?"

# Types chosen so SQLite and Postgres accept the same CREATE TABLE text.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS releases (
        dataset_id TEXT NOT NULL,
        version TEXT NOT NULL,
        visibility TEXT NOT NULL,
        package_digest TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        media_type TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (dataset_id, version)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_releases_digest
    ON releases(dataset_id, package_digest)
    """,
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
    CREATE TABLE IF NOT EXISTS organizations (
        org_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        is_claimable INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_memberships (
        org_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (org_id, user_id)
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
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        avatar_url TEXT NOT NULL DEFAULT '',
        github_id TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_invite_keys (
        key_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        token_prefix TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        max_uses INTEGER,
        use_count INTEGER NOT NULL DEFAULT 0,
        expires_at REAL,
        revoked_at REAL,
        created_at REAL NOT NULL
    )
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
    CREATE TABLE IF NOT EXISTS dataset_drafts (
        dataset_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        visibility TEXT NOT NULL,
        package_digest TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        media_type TEXT NOT NULL,
        package_kind TEXT NOT NULL DEFAULT 'dataset',
        uploaded_by TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_acl (
        dataset_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (dataset_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS package_display_names (
        dataset_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS package_download_counts (
        dataset_id TEXT PRIMARY KEY,
        download_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS package_favorites (
        user_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, dataset_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS package_icons (
        dataset_id TEXT PRIMARY KEY,
        icon_key TEXT NOT NULL DEFAULT '',
        icon_github TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
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
    CREATE TABLE IF NOT EXISTS resource_requests (
        request_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        suite_run_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        applicant TEXT NOT NULL,
        owner_org_id TEXT NOT NULL,
        agent_ref TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        decided_at REAL,
        decided_by TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_requests_inbox
    ON resource_requests(owner_org_id, status, created_at)
    """,
)

# ---- dataset draft / ACL ---------------------------------------------------

UPSERT_DRAFT = """
INSERT INTO dataset_drafts(
    dataset_id, org_id, visibility, package_digest,
    blob_digest, size, media_type, package_kind,
    uploaded_by, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(dataset_id) DO UPDATE SET
    org_id=excluded.org_id,
    visibility=excluded.visibility,
    package_digest=excluded.package_digest,
    blob_digest=excluded.blob_digest,
    size=excluded.size,
    media_type=excluded.media_type,
    package_kind=excluded.package_kind,
    uploaded_by=excluded.uploaded_by,
    updated_at=excluded.updated_at
"""

SELECT_DRAFT = "SELECT * FROM dataset_drafts WHERE dataset_id=?"

SELECT_DRAFT_BY_DIGEST = "SELECT * FROM dataset_drafts WHERE dataset_id=? AND package_digest=?"

LIST_DRAFTS = "SELECT * FROM dataset_drafts ORDER BY dataset_id"

DELETE_DRAFT = "DELETE FROM dataset_drafts WHERE dataset_id=?"

UPSERT_DATASET_ACL = """
INSERT INTO dataset_acl(dataset_id, user_id, role, created_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(dataset_id, user_id) DO UPDATE SET
    role=excluded.role
"""

SELECT_DATASET_ACL = "SELECT * FROM dataset_acl WHERE dataset_id=? AND user_id=?"

LIST_DATASET_ACL = "SELECT * FROM dataset_acl WHERE dataset_id=? ORDER BY role, user_id"

LIST_DATASET_ACL_FOR_USER = (
    "SELECT * FROM dataset_acl WHERE user_id=? AND role IN ('owner', 'collaborator') "
    "ORDER BY dataset_id"
)

DELETE_DATASET_ACL = "DELETE FROM dataset_acl WHERE dataset_id=? AND user_id=?"

# Live Postgres may have created these as BOOLEAN; inserts bind 0/1 (INTEGER).
SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = (
    ("organizations", "is_claimable"),
    ("suite_results", "board_listed"),
)

# (table, column, sqlite/postgres-compatible type clause)
SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("suite_results", "config_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("releases", "org_id", "TEXT"),
    ("attempt_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "suite_run_id", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "environment", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "agent_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "model_label", "TEXT NOT NULL DEFAULT ''"),
    ("attempt_results", "score", "REAL"),
    ("suite_results", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "complete", "INTEGER NOT NULL DEFAULT 0"),
    ("suite_results", "bound_kind", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("suite_results", "task_set_digest", "TEXT NOT NULL DEFAULT ''"),
    ("suite_results", "board_listed", "INTEGER NOT NULL DEFAULT 0"),
    ("releases", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("organizations", "description", "TEXT NOT NULL DEFAULT ''"),
    ("user_profiles", "description", "TEXT NOT NULL DEFAULT ''"),
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
INSERT_RESOURCE_REQUEST = """
INSERT INTO resource_requests(
    request_id, kind, status, suite_run_id, dataset_id, applicant,
    owner_org_id, agent_ref, created_at, decided_at, decided_by
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
SELECT_RESOURCE_REQUEST = "SELECT * FROM resource_requests WHERE request_id=?"
LIST_RESOURCE_REQUESTS_BY_IDS = (
    "SELECT * FROM resource_requests WHERE request_id IN ({placeholders})"
)
LIST_INBOX_REQUESTS = (
    "SELECT * FROM resource_requests WHERE owner_org_id IN ({placeholders}) "
    "AND status=? ORDER BY created_at DESC"
)
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
SELECT_ATTEMPTS_FOR_SUITE = (
    "SELECT * FROM attempt_results WHERE suite_run_id=? ORDER BY created_at DESC"
)
COUNT_ATTEMPT_BLOB_REFS = "SELECT COUNT(*) AS n FROM attempt_results WHERE blob_digest=?"
COUNT_SUITE_BLOB_REFS = "SELECT COUNT(*) AS n FROM suite_results WHERE blob_digest=?"
COUNT_PACKAGE_BLOB_REFS = "SELECT COUNT(*) AS n FROM releases WHERE blob_digest=?"
COUNT_DRAFT_BLOB_REFS = "SELECT COUNT(*) AS n FROM dataset_drafts WHERE blob_digest=?"
DELETE_RELEASE = "DELETE FROM releases WHERE dataset_id=? AND version=?"
UPDATE_RELEASE_VISIBILITY = "UPDATE releases SET visibility=? WHERE dataset_id=? AND version=?"

SELECT_USER_ORGS = """
SELECT o.*, m.role AS membership_role
FROM organizations o
JOIN org_memberships m ON m.org_id = o.org_id
WHERE m.user_id = ?
ORDER BY o.name
"""
SELECT_ORG_HAS_OWNER = "SELECT 1 FROM org_memberships WHERE org_id=? AND role='owner' LIMIT 1"
INSERT_ORG_MEMBERSHIP_OWNER = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'owner', ?)
"""
UPDATE_ORG_CLAIMED = "UPDATE organizations SET is_claimable=0 WHERE org_id=?"
INSERT_ORG_MEMBERSHIP = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, ?, ?)
"""
DELETE_ORG_MEMBERSHIP = "DELETE FROM org_memberships WHERE org_id=? AND user_id=?"
UPDATE_ORG_MEMBERSHIP_ROLE = "UPDATE org_memberships SET role=? WHERE org_id=? AND user_id=?"
COUNT_ORG_OWNERS = "SELECT COUNT(*) AS n FROM org_memberships WHERE org_id=? AND role='owner'"
COUNT_ORG_PACKAGES = "SELECT COUNT(*) AS n FROM releases WHERE org_id=?"
DELETE_ORG_INVITE_KEYS = "DELETE FROM org_invite_keys WHERE org_id=?"
DELETE_ORG_MEMBERSHIPS = "DELETE FROM org_memberships WHERE org_id=?"
DELETE_ORG_RESULT_SHARES = "DELETE FROM result_shares WHERE target_type='org' AND target_id=?"
DELETE_ORG = "DELETE FROM organizations WHERE org_id=?"
SELECT_ORG_MEMBERS = """
SELECT org_id, user_id, role, created_at
FROM org_memberships
WHERE org_id=?
ORDER BY CASE WHEN role = 'owner' THEN 0 ELSE 1 END, user_id
"""
INSERT_INVITE_KEY = """
INSERT INTO org_invite_keys(
    key_id, org_id, token_hash, token_prefix, created_by,
    max_uses, use_count, expires_at, revoked_at, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
SELECT_INVITE_KEYS = """
SELECT * FROM org_invite_keys
WHERE org_id=?
ORDER BY created_at DESC
"""
SELECT_INVITE_KEY = "SELECT * FROM org_invite_keys WHERE org_id=? AND key_id=?"
UPDATE_INVITE_REVOKED = "UPDATE org_invite_keys SET revoked_at=? WHERE key_id=?"
SELECT_INVITE_BY_HASH = "SELECT * FROM org_invite_keys WHERE token_hash=?"
CLAIM_INVITE_USE = """
UPDATE org_invite_keys
SET use_count = use_count + 1
WHERE key_id=? AND (max_uses IS NULL OR use_count < max_uses)
"""
INSERT_ORG_MEMBERSHIP_MEMBER = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'member', ?)
"""
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
UPSERT_USER_PROFILE = """
INSERT INTO user_profiles(
    user_id, display_name, avatar_url, github_id, description, updated_at
) VALUES (?, ?, ?, ?, '', ?)
ON CONFLICT(user_id) DO UPDATE SET
    display_name=excluded.display_name,
    avatar_url=excluded.avatar_url,
    github_id=excluded.github_id,
    updated_at=excluded.updated_at
"""
SELECT_USER_PROFILE = "SELECT * FROM user_profiles WHERE user_id=?"
UPSERT_USER_DESCRIPTION = """
INSERT INTO user_profiles(
    user_id, display_name, avatar_url, github_id, description, updated_at
) VALUES (?, '', '', '', ?, ?)
ON CONFLICT(user_id) DO UPDATE SET
    description=excluded.description,
    updated_at=excluded.updated_at
"""
INCREMENT_PACKAGE_DOWNLOAD = """
INSERT INTO package_download_counts(dataset_id, download_count)
VALUES (?, 1)
ON CONFLICT(dataset_id) DO UPDATE SET
    download_count = package_download_counts.download_count + 1
"""
INSERT_PACKAGE_FAVORITE = """
INSERT INTO package_favorites(user_id, dataset_id, created_at)
VALUES (?, ?, ?)
ON CONFLICT(user_id, dataset_id) DO NOTHING
"""
DELETE_PACKAGE_FAVORITE = "DELETE FROM package_favorites WHERE user_id=? AND dataset_id=?"


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


def select_user_profiles_in_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return f"SELECT * FROM user_profiles WHERE user_id IN ({placeholders})"


def select_package_download_counts_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return (
        "SELECT dataset_id, download_count FROM package_download_counts "
        f"WHERE dataset_id IN ({placeholders})"
    )


def select_package_favorite_counts_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return (
        "SELECT dataset_id, COUNT(*) AS favorite_count FROM package_favorites "
        f"WHERE dataset_id IN ({placeholders}) GROUP BY dataset_id"
    )


def select_package_favorites_for_user_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return (
        "SELECT dataset_id FROM package_favorites "
        f"WHERE user_id=? AND dataset_id IN ({placeholders})"
    )


def select_result_shared_orgs_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return f"""
                SELECT 1 FROM result_shares
                WHERE result_kind=? AND result_id=? AND target_type='org'
                  AND target_id IN ({placeholders})
                LIMIT 1
                """
