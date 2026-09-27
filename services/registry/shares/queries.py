"""Snapshot share SQL."""

from __future__ import annotations

INSERT_SNAPSHOT_SHARE = """
INSERT INTO snapshot_shares(
    token, owner_user_id, suite_run_id, dataset_id, dataset_version,
    blob_digest, size, summary_json, created_at, run_id, mode, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_SNAPSHOT_SHARE = "SELECT * FROM snapshot_shares WHERE token=?"

SELECT_SNAPSHOT_SHARE_FOR_OWNER = """
SELECT * FROM snapshot_shares
WHERE owner_user_id=? AND suite_run_id=? AND run_id=?
ORDER BY created_at DESC
LIMIT 1
"""

DELETE_SNAPSHOT_SHARE = "DELETE FROM snapshot_shares WHERE token=?"

UPDATE_SNAPSHOT_SHARE = """
UPDATE snapshot_shares
SET summary_json=?, size=?, updated_at=?
WHERE token=?
"""

COUNT_SNAPSHOT_SHARE_BLOB = "SELECT COUNT(*) AS n FROM snapshot_shares WHERE blob_digest=?"

LIST_SNAPSHOT_SHARE_FILES = """
SELECT token, path, blob_digest, size
FROM snapshot_share_files
WHERE token=?
ORDER BY path
"""

SELECT_SNAPSHOT_SHARE_FILE = """
SELECT token, path, blob_digest, size
FROM snapshot_share_files
WHERE token=? AND path=?
"""

UPSERT_SNAPSHOT_SHARE_FILE = """
INSERT INTO snapshot_share_files(token, path, blob_digest, size)
VALUES (?, ?, ?, ?)
ON CONFLICT(token, path) DO UPDATE SET
    blob_digest=excluded.blob_digest,
    size=excluded.size
"""

DELETE_SNAPSHOT_SHARE_FILES = "DELETE FROM snapshot_share_files WHERE token=?"

COUNT_SNAPSHOT_SHARE_FILE_BLOB = (
    "SELECT COUNT(*) AS n FROM snapshot_share_files WHERE blob_digest=?"
)

SCHEMA_STATEMENTS: tuple[str, ...] = (
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
        run_id TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL DEFAULT 'static',
        updated_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshot_shares_blob
    ON snapshot_shares(blob_digest)
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_share_files (
        token TEXT NOT NULL,
        path TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        PRIMARY KEY (token, path)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshot_share_files_blob
    ON snapshot_share_files(blob_digest)
    """,
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("snapshot_shares", "run_id", "TEXT NOT NULL DEFAULT ''"),
    ("snapshot_shares", "mode", "TEXT NOT NULL DEFAULT 'static'"),
    ("snapshot_shares", "updated_at", "REAL NOT NULL DEFAULT 0"),
)
