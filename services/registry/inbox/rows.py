"""Resource request row."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True, slots=True)
class ResourceRequestRow:
    request_id: str
    kind: str
    status: str
    suite_run_id: str
    dataset_id: str
    applicant: str
    owner_org_id: str
    agent_ref: str
    created_at: float
    decided_at: float | None = None
    decided_by: str = ""
    canonical_model: str = ""

def request_to_dict(row: ResourceRequestRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "request_id": row.request_id,
        "kind": row.kind,
        "status": row.status,
        "suite_run_id": row.suite_run_id,
        "dataset_id": row.dataset_id,
        "applicant": row.applicant,
        "owner_org_id": row.owner_org_id,
        "created_at": row.created_at,
    }
    if row.agent_ref:
        out["agent_ref"] = row.agent_ref
    if row.canonical_model:
        out["canonical_model"] = row.canonical_model
    if row.decided_at is not None:
        out["decided_at"] = row.decided_at
    if row.decided_by:
        out["decided_by"] = row.decided_by
    return out
