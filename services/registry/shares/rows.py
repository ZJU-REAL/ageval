"""Snapshot share row. Not a result_shares or visibility row."""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SnapshotShareRow:
    """Read link. Not a suite visibility or result_shares row.

    ``mode`` is ``static`` (one archive) or ``live`` (mutable summary plus
    per-path objects). ``blob_digest`` is the archive for static and empty
    for live.
    """

    token: str
    owner_user_id: str
    suite_run_id: str
    dataset_id: str
    dataset_version: str
    blob_digest: str
    size: int
    summary_json: str
    created_at: float
    run_id: str = ""
    mode: str = "static"
    updated_at: float = 0.0


@dataclass(frozen=True, slots=True)
class SnapshotShareFileRow:
    """One path inside a live share. Content-addressed under the shares prefix."""

    token: str
    path: str
    blob_digest: str
    size: int
