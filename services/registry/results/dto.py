"""Attempt and suite DTO helpers."""

from __future__ import annotations

import json
from typing import Any

from services.registry.results.rows import (
    AttemptResultRow,
    ResultShareRow,
    SuiteResultRow,
)

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
    out["error"] = _load_error_json(row.error_json)
    out["limit"] = row.limit_name or None
    return out

def _load_error_json(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)

def share_to_dict(row: ResultShareRow) -> dict[str, Any]:
    return {
        "result_kind": row.result_kind,
        "result_id": row.result_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "created_at": row.created_at,
    }

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
