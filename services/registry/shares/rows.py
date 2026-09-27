"""Snapshot share row. Not a result_shares or visibility row."""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SnapshotShareRow:
    """One-shot read link. Not a suite visibility or result_shares row."""

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
