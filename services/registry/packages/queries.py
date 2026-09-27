"""Package release, draft, ACL, and marketplace SQL."""

from __future__ import annotations

from typing import Any

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

UPSERT_PACKAGE_TASK_SUMMARY = """
INSERT INTO package_task_summaries(
    package_digest, has_shared, tasks_json, overlay_prefixes_json, description,
    created_at
)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(package_digest) DO UPDATE SET
    has_shared=excluded.has_shared,
    tasks_json=excluded.tasks_json,
    overlay_prefixes_json=excluded.overlay_prefixes_json,
    description=excluded.description
"""

SELECT_PACKAGE_TASK_SUMMARY = (
    "SELECT has_shared, tasks_json, overlay_prefixes_json "
    "FROM package_task_summaries WHERE package_digest=?"
)

DELETE_PACKAGE_TASK_SUMMARY = "DELETE FROM package_task_summaries WHERE package_digest=?"

COUNT_PACKAGE_DIGEST_REFS = """
SELECT (
    (SELECT COUNT(*) FROM releases WHERE package_digest=?)
    + (SELECT COUNT(*) FROM dataset_drafts WHERE package_digest=?)
) AS n
"""

SELECT_SUITE_TASK_REFS = """
SELECT suite_run_id, visibility, uploaded_by, created_at, tasks_json
FROM suite_results WHERE dataset_id=?
"""

UPSERT_PACKAGE_DISPLAY_NAME = """
INSERT INTO package_display_names(dataset_id, display_name, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(dataset_id) DO UPDATE SET
    display_name=excluded.display_name,
    updated_at=excluded.updated_at
"""

SELECT_PACKAGE_DISPLAY_NAME = "SELECT display_name FROM package_display_names WHERE dataset_id=?"

SELECT_PACKAGE_DISPLAY_NAMES = "SELECT dataset_id, display_name FROM package_display_names"

UPSERT_PACKAGE_DESCRIPTION = """
INSERT INTO package_descriptions(dataset_id, description, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(dataset_id) DO UPDATE SET
    description=excluded.description,
    updated_at=excluded.updated_at
"""

SELECT_PACKAGE_DESCRIPTION = "SELECT description FROM package_descriptions WHERE dataset_id=?"

SELECT_PACKAGE_DESCRIPTIONS = "SELECT dataset_id, description FROM package_descriptions"

DELETE_PACKAGE_DESCRIPTION = "DELETE FROM package_descriptions WHERE dataset_id=?"

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

COUNT_PACKAGE_BLOB_REFS = "SELECT COUNT(*) AS n FROM releases WHERE blob_digest=?"

COUNT_DRAFT_BLOB_REFS = "SELECT COUNT(*) AS n FROM dataset_drafts WHERE blob_digest=?"

DELETE_RELEASE = "DELETE FROM releases WHERE dataset_id=? AND version=?"

UPDATE_RELEASE_VISIBILITY = "UPDATE releases SET visibility=? WHERE dataset_id=? AND version=?"

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
    CREATE TABLE IF NOT EXISTS package_descriptions (
        dataset_id TEXT PRIMARY KEY,
        description TEXT NOT NULL DEFAULT '',
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
    CREATE TABLE IF NOT EXISTS package_task_summaries (
        package_digest TEXT PRIMARY KEY,
        has_shared INTEGER NOT NULL,
        tasks_json TEXT NOT NULL,
        overlay_prefixes_json TEXT,
        description TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    )
    """,
)

SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = ()

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("releases", "org_id", "TEXT"),
    ("releases", "uploaded_by", "TEXT NOT NULL DEFAULT ''"),
    ("package_task_summaries", "overlay_prefixes_json", "TEXT"),
    ("package_task_summaries", "description", "TEXT NOT NULL DEFAULT ''"),
)
