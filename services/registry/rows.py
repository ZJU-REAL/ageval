"""Row dataclasses shared by the Registry aggregate stores."""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------





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










# ---------------------------------------------------------------------------
# Metadata (packages + attempt results + orgs + shares)
