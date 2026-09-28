"""Snapshot share persistence."""

from __future__ import annotations

from typing import Any

from services.registry.shares import queries as Q
from services.registry.shares.protocol import ShareStoreProtocol
from services.registry.shares.rows import SnapshotShareRow


class ShareStore(ShareStoreProtocol):
    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def insert_snapshot_share(self, row: SnapshotShareRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_SNAPSHOT_SHARE,
                    (
                        row.token,
                        row.owner_user_id,
                        row.suite_run_id,
                        row.dataset_id,
                        row.dataset_version,
                        row.blob_digest,
                        row.size,
                        row.summary_json,
                        row.created_at,
                        row.run_id,
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("snapshot share already exists") from exc
    def get_snapshot_share(self, token: str) -> SnapshotShareRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SNAPSHOT_SHARE, (token,))
            found = cur.fetchone()
            return self._snapshot_share_row(found) if found else None
    def find_snapshot_share(
        self, *, owner_user_id: str, suite_run_id: str, run_id: str
    ) -> SnapshotShareRow | None:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_SNAPSHOT_SHARE_FOR_OWNER,
                (owner_user_id, suite_run_id, run_id),
            )
            found = cur.fetchone()
            return self._snapshot_share_row(found) if found else None
    def delete_snapshot_share(self, token: str) -> SnapshotShareRow:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SNAPSHOT_SHARE, (token,))
            found = cur.fetchone()
            if found is None:
                raise LookupError("snapshot share not found")
            row = self._snapshot_share_row(found)
            self._exec(conn, Q.DELETE_SNAPSHOT_SHARE, (token,))
            conn.commit()
            return row
    def count_snapshot_share_blob_refs(self, blob_digest: str) -> int:
        with self._connect() as conn:
            cur = self._exec(conn, Q.COUNT_SNAPSHOT_SHARE_BLOB, (blob_digest,))
            found = cur.fetchone()
            if found is None:
                return 0
            return int(found["n"])
    @staticmethod
    def _snapshot_share_row(record: Any) -> SnapshotShareRow:
        return SnapshotShareRow(
            token=str(record["token"]),
            owner_user_id=str(record["owner_user_id"]),
            suite_run_id=str(record["suite_run_id"]),
            dataset_id=str(record["dataset_id"]),
            dataset_version=str(record["dataset_version"]),
            blob_digest=str(record["blob_digest"]),
            size=int(record["size"]),
            summary_json=str(record["summary_json"]),
            created_at=float(record["created_at"]),
            run_id=str(record["run_id"] or ""),
        )
