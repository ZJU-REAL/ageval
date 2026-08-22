"""Derived Agent appearances over official public Leaderboard suites.

Nobody stores a Runtime or appearance row. Reduce is here; HTTP stays thin.
Group key is the published Hub id ``org/name`` parsed from ``agent_ref``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.registry.dataset import BOUND_RELEASE
from services.registry.official import official_dataset_ids
from services.registry.store import TokenInfo

from ageval.agents.refs import published_agent_ref_parts
from ageval.config.runtime_identity import (
    agent_display_name,
    resolve_agent_id,
)


def is_plaza_source_suite(payload: Mapping[str, Any], official_ids: frozenset[str]) -> bool:
    """Public complete release-bound suite on an official Dataset."""
    return (
        payload.get("visibility") == "public"
        and bool(payload.get("complete"))
        and payload.get("bound_kind") == BOUND_RELEASE
        and str(payload.get("dataset_id") or "") in official_ids
    )


def attach_agent_refs(
    payload: dict[str, Any],
    official_ids: frozenset[str],
    *,
    consented: set[str] | None = None,
) -> dict[str, Any]:
    """Add ``agent_refs`` only on plaza-source rows with consented published refs."""
    if not is_plaza_source_suite(payload, official_ids):
        return payload
    refs = _agent_refs_from_overlay(
        payload.get("job_overlay") if isinstance(payload.get("job_overlay"), Mapping) else None
    )
    if consented is not None:
        refs = [r for r in refs if r.get("package_id") in consented]
    if refs:
        payload["agent_refs"] = refs
    return payload


class RuntimeService:
    def __init__(self, meta: Any, results: Any) -> None:
        self.meta = meta
        self.results = results

    def appearances_for_agent(self, package_id: str, auth: TokenInfo) -> list[dict[str, Any]]:
        """Appearances whose ``agent_ref`` parses to *package_id* (``org/name``)."""
        want = (package_id or "").strip()
        if not want:
            return []
        grouped = self._reduce(auth)
        rows = grouped.get(want) or []
        return sorted(
            rows,
            key=lambda a: (
                str(a.get("agent_version") or ""),
                -float(a.get("created_at") or 0),
                str(a.get("role") or ""),
            ),
        )

    def _reduce(self, auth: TokenInfo) -> dict[str, list[dict[str, Any]]]:
        official = official_dataset_ids(self.meta.list_releases(include_private=True))
        listed = self.results.list_suites(auth=auth, dataset_id=None)
        items = [s for s in (listed.get("items") or []) if isinstance(s, Mapping)]
        suite_ids = [str(s.get("suite_run_id") or "") for s in items]
        consents = self.meta.list_agent_consents_for_suites(suite_ids)
        grouped: dict[str, list[dict[str, Any]]] = {}
        digest_cache: dict[tuple[str, str], str] = {}
        for suite in items:
            if not is_plaza_source_suite(suite, official):
                continue
            sid = str(suite.get("suite_run_id") or "")
            allowed = consents.get(sid) or set()
            package_digest = _package_digest_for_suite(self.meta, suite, digest_cache)
            for appearance in _appearances_from_suite(suite, package_digest=package_digest):
                pid = str(appearance.get("package_id") or "")
                if not pid or pid not in allowed:
                    continue
                grouped.setdefault(pid, []).append(appearance)
        return grouped


def _agent_refs_from_overlay(overlay: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(overlay, Mapping):
        return []
    profiles = overlay.get("agent_profiles")
    if not isinstance(profiles, Mapping):
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for role, raw in profiles.items():
        if not isinstance(raw, Mapping):
            continue
        parts = published_agent_ref_parts(raw.get("agent_ref"))
        if parts is None:
            continue
        package_id, _version = parts
        role_id = str(role).strip()
        if not role_id:
            continue
        key = (role_id, package_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({"role": role_id, "package_id": package_id})
    return out


def _package_digest_for_suite(
    meta: Any,
    suite: Mapping[str, Any],
    cache: dict[tuple[str, str], str],
) -> str:
    dataset_id = str(suite.get("dataset_id") or "")
    version = str(suite.get("dataset_version") or "")
    if not dataset_id or not version:
        return ""
    key = (dataset_id, version)
    if key in cache:
        return cache[key]
    digest = ""
    try:
        release = meta.get_by_version(dataset_id, version)
    except Exception:  # noqa: BLE001 — appearance stays YAML-only
        release = None
    if release is not None:
        digest = str(getattr(release, "package_digest", "") or "")
    cache[key] = digest
    return digest


def _overlay_paths(binding: Mapping[str, Any]) -> list[str]:
    raw = binding.get("overlays")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _appearances_from_suite(
    suite: Mapping[str, Any],
    *,
    package_digest: str = "",
) -> list[dict[str, Any]]:
    overlay = suite.get("job_overlay")
    if not isinstance(overlay, Mapping):
        return []
    profiles = overlay.get("agent_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        return []
    teammates_all: list[dict[str, str]] = []
    valid: list[tuple[str, Mapping[str, Any], tuple[str, str]]] = []
    for role, raw in profiles.items():
        if not isinstance(raw, Mapping):
            continue
        role_id = str(role).strip()
        if not role_id:
            continue
        teammates_all.append(
            {
                "role": role_id,
                "executor": str(raw.get("executor") or "").strip(),
                "entry": resolve_agent_id(raw),
                "display_name": agent_display_name(raw),
            }
        )
        parts = published_agent_ref_parts(raw.get("agent_ref"))
        if parts is None:
            continue
        valid.append((role_id, raw, parts))
    if not valid:
        return []
    metrics = suite.get("metrics")
    metrics_out = dict(metrics) if isinstance(metrics, Mapping) else {}
    out: list[dict[str, Any]] = []
    for role_id, raw, parts in valid:
        package_id, agent_version = parts
        model = raw.get("model")
        agent_ref = raw.get("agent_ref")
        row: dict[str, Any] = {
            "package_id": package_id,
            "agent_version": agent_version,
            "dataset_id": str(suite.get("dataset_id") or ""),
            "dataset_version": str(suite.get("dataset_version") or ""),
            "suite_run_id": str(suite.get("suite_run_id") or ""),
            "role": role_id,
            "model": model.strip() if isinstance(model, str) else "",
            "pass_rate": suite.get("pass_rate"),
            "mean_score": suite.get("mean_score"),
            "metrics": metrics_out,
            "uploaded_by": str(suite.get("uploaded_by") or ""),
            "created_at": suite.get("created_at"),
            "teammates": [t for t in teammates_all if t["role"] != role_id],
            "agent_ref": str(agent_ref).strip() if isinstance(agent_ref, str) else "",
        }
        if package_digest:
            row["package_digest"] = package_digest
        overlays = _overlay_paths(raw)
        if overlays:
            row["overlays"] = overlays
        out.append(row)
    return out
