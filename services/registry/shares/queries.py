"""Snapshot share SQL."""

from __future__ import annotations

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
        run_id TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshot_shares_blob
    ON snapshot_shares(blob_digest)
    """,
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("snapshot_shares", "run_id", "TEXT NOT NULL DEFAULT ''"),
)
