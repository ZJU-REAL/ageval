"""Registry metadata, tokens, results, and blob storage.

Unit tests: SQLite + Memory blob.
Compose / production: Postgres + S3-compatible (RustFS).

Raw API tokens are never persisted — only sha256 digests.
Visibility is only ``public`` | ``private``.
Packages require ``org_id`` on new publishes; results carry ``uploaded_by``
and optional share targets (org / user). Private read is ownership/membership
based (admin bypass); scopes alone no longer grant global private sight.

Blob and token adapters live in ``blobs.py`` / ``tokens.py``; the four
aggregate stores live in ``store_*.py`` behind the narrow protocols.
This module keeps the row/DTO vocabulary and re-exports while importers
migrate.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from services.registry.blobs import (  # noqa: F401
    FilesystemBlobStore,
    MemoryBlobStore,
    S3BlobStore,
)
from services.registry.clock import now
from services.registry.rows import (  # noqa: F401
    AttemptResultRow,
    DatasetAclRow,
    DraftRow,
    MembershipRow,
    OrgInviteKeyRow,
    OrgRow,
    ReleaseRow,
    ResourceRequestRow,
    ResultShareRow,
    SuiteResultRow,
    UserProfileRow,
)
from services.registry.store_schema import (  # noqa: F401
    RegistryStores,
    open_sqlite_stores,
    open_stores,
)
from services.registry.tokens import (  # noqa: F401
    ADMIN_SCOPES,
    DEFAULT_LOGIN_SCOPES,
    PersistentTokenStore,
    PostgresTokenStore,
    SqliteTokenStore,
    TokenInfo,
    TokenStore,
    _normalize_user_id,
)


# ---------------------------------------------------------------------------
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
    from services.registry.official import is_official_upload_org

    out["official"] = is_official_upload_org(row.org_id)
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    if row.version == "draft":
        out["slot"] = "draft"
        out["is_draft"] = True
    return out


def attempt_to_dict(row: AttemptResultRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "run_id": row.run_id,
        "dataset_id": row.dataset_id,
        "dataset_version": row.dataset_version,
        "task_id": row.task_id,
        "lock_digest": row.lock_digest,
        "status": row.status,
        "visibility": row.visibility,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "created_at": row.created_at,
    }
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    if row.suite_run_id:
        out["suite_run_id"] = row.suite_run_id
    if row.environment:
        out["environment"] = row.environment
    if row.agent_label:
        out["agent_label"] = row.agent_label
    if row.model_label:
        out["model_label"] = row.model_label
    if row.score is not None:
        out["score"] = row.score
    return out


def org_to_dict(row: OrgRow) -> dict[str, Any]:
    from services.registry.official import is_official_upload_org

    out: dict[str, Any] = {
        "org_id": row.org_id,
        "name": row.name,
        "display_name": row.display_name,
        "description": row.description,
        "is_claimable": row.is_claimable,
        "created_at": row.created_at,
        "official": is_official_upload_org(row.org_id),
    }
    if row.icon_key:
        out["icon_key"] = row.icon_key
    if row.icon_github:
        out["icon_github"] = row.icon_github
    return out


def membership_to_dict(
    row: MembershipRow,
    *,
    profile: UserProfileRow | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "org_id": row.org_id,
        "user_id": row.user_id,
        "role": row.role,
        "created_at": row.created_at,
    }
    if profile is not None:
        if profile.display_name:
            out["display_name"] = profile.display_name
        if profile.avatar_url:
            out["avatar_url"] = profile.avatar_url
        if profile.github_id:
            out["github_id"] = profile.github_id
    return out


def invite_key_to_dict(
    row: OrgInviteKeyRow,
    *,
    invite_key: str | None = None,
) -> dict[str, Any]:
    """Serialize invite key metadata for owner APIs.

    Pass ``invite_key`` only on create so the secret is returned once.
    List/revoke omit it; storage keeps hash + prefix only.
    """
    out: dict[str, Any] = {
        "key_id": row.key_id,
        "org_id": row.org_id,
        "token_prefix": row.token_prefix,
        "created_by": row.created_by,
        "max_uses": row.max_uses,
        "use_count": row.use_count,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "active": row.revoked_at is None
        and (row.expires_at is None or row.expires_at > now())
        and (row.max_uses is None or row.use_count < row.max_uses),
    }
    if invite_key:
        out["invite_key"] = invite_key
    return out


def share_to_dict(row: ResultShareRow) -> dict[str, Any]:
    return {
        "result_kind": row.result_kind,
        "result_id": row.result_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "created_at": row.created_at,
    }


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


def suite_to_dict(
    row: SuiteResultRow,
    *,
    attempt_content_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Serialize suite result; never invent a suite-level PASS field.

    When *attempt_content_ids* is provided, each task_ref gains
    ``has_attempt_content`` (bool) for Hub Jobs deep-link readiness (#43).
    Callers must pass only attempt ids visible to the current principal
    (never invent true for private/unshared rows).
    """
    try:
        metrics = json.loads(row.metrics_json)
    except (json.JSONDecodeError, TypeError):
        metrics = {}
    try:
        task_refs = json.loads(row.tasks_json)
    except (json.JSONDecodeError, TypeError):
        task_refs = []
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(task_refs, list):
        task_refs = []
    if attempt_content_ids is not None:
        enriched: list[Any] = []
        for ref in task_refs:
            if not isinstance(ref, dict):
                enriched.append(ref)
                continue
            item = dict(ref)
            rid = item.get("run_id")
            rid_s = str(rid).strip() if rid is not None else ""
            item["has_attempt_content"] = bool(rid_s and rid_s in attempt_content_ids)
            enriched.append(item)
        task_refs = enriched
    out: dict[str, Any] = {
        "suite_run_id": row.suite_run_id,
        "dataset_id": row.dataset_id,
        "dataset_version": row.dataset_version,
        "visibility": row.visibility,
        "pass_rate": row.pass_rate,
        "mean_score": row.mean_score,
        "metrics": metrics,
        "task_refs": task_refs,
        "agent_label": row.agent_label,
        "model_label": row.model_label,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "exit_code": row.exit_code,
        "created_at": row.created_at,
        "complete": bool(row.complete),
        "bound_kind": row.bound_kind or "unknown",
        # Explicit: no suite PASS authority
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    if row.task_set_digest:
        out["task_set_digest"] = row.task_set_digest
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    out["board_listed"] = bool(row.board_listed)
    # #42 config fingerprint projection (absent on legacy rows)
    try:
        cfg = json.loads(row.config_json or "{}")
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    if isinstance(cfg, dict):
        if cfg.get("config_fingerprint"):
            out["config_fingerprint"] = cfg["config_fingerprint"]
        if "config_homogeneous" in cfg:
            out["config_homogeneous"] = bool(cfg["config_homogeneous"])
        actors = cfg.get("actors_summary")
        if isinstance(actors, list):
            out["actors_summary"] = actors
        # #59 secret-free job binding for Hub rehydrate
        overlay = cfg.get("job_overlay")
        if isinstance(overlay, dict) and overlay:
            out["job_overlay"] = overlay
        plugins = cfg.get("plugins")
        if isinstance(plugins, list) and plugins:
            out["plugins"] = plugins
    if any(
        isinstance(ref, dict) and isinstance(ref.get("previous"), list) and ref["previous"]
        for ref in task_refs
    ):
        out["amended"] = True
    return out


def _run_ids_from_tasks_json(tasks_json: str) -> list[str]:
    try:
        refs = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        rid = ref.get("run_id")
        if rid is None:
            continue
        text = str(rid).strip()
        if text:
            out.append(text)
    return out
