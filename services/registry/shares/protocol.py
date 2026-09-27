"""Snapshot share store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.shares.rows import SnapshotShareRow


@runtime_checkable
class ShareStoreProtocol(Protocol):
    def insert_snapshot_share(self, row: SnapshotShareRow) -> None: ...
    def get_snapshot_share(self, token: str) -> SnapshotShareRow | None: ...
    def find_snapshot_share(
        self, *, owner_user_id: str, suite_run_id: str, run_id: str
    ) -> SnapshotShareRow | None: ...
    def delete_snapshot_share(self, token: str) -> SnapshotShareRow: ...
    def count_snapshot_share_blob_refs(self, blob_digest: str) -> int: ...
