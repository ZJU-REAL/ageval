"""Package release DTO helpers."""

from __future__ import annotations

import contextlib
from typing import Any

from services.registry.packages.rows import ReleaseRow

def package_kind_for_media_type(media_type: str) -> str:
    """Derive list/meta ``package_kind`` from the current vnd.ageval types only."""
    from ageval.registry.media_types import (
        AGENT_MEDIA_TYPE,
        DATASET_MEDIA_TYPE,
        PLUGIN_MEDIA_TYPE,
    )

    if media_type == PLUGIN_MEDIA_TYPE:
        return "plugin"
    if media_type == AGENT_MEDIA_TYPE:
        return "agent"
    if media_type == DATASET_MEDIA_TYPE:
        return "dataset"
    raise ValueError(f"unknown package media_type: {media_type!r}")

def release_to_dict(row: ReleaseRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dataset_id": row.dataset_id,
        "version": row.version,
        "visibility": row.visibility,
        "package_digest": row.package_digest,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "media_type": row.media_type,
        "created_at": row.created_at,
    }
    with contextlib.suppress(ValueError):
        out["package_kind"] = package_kind_for_media_type(row.media_type)
    if row.org_id:
        out["org_id"] = row.org_id
    from services.registry.orgs.official import is_official_upload_org

    out["official"] = is_official_upload_org(row.org_id)
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    if row.version == "draft":
        out["slot"] = "draft"
        out["is_draft"] = True
    return out
