"""Registry row types and DTO helpers.

Unit tests: SQLite + Memory blob.
Compose / production: Postgres + S3-compatible (RustFS).

Raw API tokens are never persisted — only sha256 digests.
Visibility is only ``public`` | ``private``.
Packages require ``org_id`` on new publishes; results carry ``uploaded_by``
and optional share targets (org / user). Private read is ownership/membership
based (admin bypass); scopes alone no longer grant global private sight.

Blob stores live in ``content/blobs.py``. Schema init lives in ``db/schema.py``.
Token adapters live in ``auth/tokens.py``. Org rows and org SQL live under ``orgs/``.
"""

from __future__ import annotations

from typing import Any

from services.registry.clock import now
from services.registry.rows import (  # noqa: F401
    ResourceRequestRow,
)

# ---------------------------------------------------------------------------








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



