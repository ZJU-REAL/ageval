"""Derived Agent Performance over plaza and consented suite rows.

Nobody stores a Runtime or Performance row. Reduce is here; HTTP stays thin.
Uploaded packs group by published Hub id ``org/name`` from ``agent_ref``
(with Agent-org consent). Builtin mechanism cards group by
``resolve_agent_id``; collect mode defaults to official plaza.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.registry.dataset import BOUND_RELEASE
from services.registry.maintainers import (
    COLLECT_MODES,
    COLLECT_OFFICIAL,
    COLLECT_OFFICIAL_AND_PERSONAL,
    DEFAULT_BUILTIN_COLLECT,
    auth_is_maintainer,
)
from services.registry.official import official_dataset_ids
from services.registry.store import TokenInfo

from ageval.agents.refs import published_agent_ref_parts
from ageval.agents.reserved import canonical_harness_id
from ageval.application.suite.attach_agent_ref import hub_agent_ref_parts
from ageval.config.runtime_identity import (
    agent_display_name,
    resolve_agent_id,
)


def is_public_complete_release(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("visibility") == "public"
        and bool(payload.get("complete"))
        and payload.get("bound_kind") == BOUND_RELEASE
    )


def is_plaza_source_suite(payload: Mapping[str, Any], official_ids: frozenset[str]) -> bool:
    """Public complete release-bound suite on an official Dataset."""
    return (
        is_public_complete_release(payload) and str(payload.get("dataset_id") or "") in official_ids
    )


def is_personal_source_suite(payload: Mapping[str, Any], official_ids: frozenset[str]) -> bool:
    """Public complete release-bound suite on a non-official Dataset."""
    dataset_id = str(payload.get("dataset_id") or "")
    return (
        is_public_complete_release(payload) and bool(dataset_id) and dataset_id not in official_ids
    )


def attach_agent_refs(
    payload: dict[str, Any],
    official_ids: frozenset[str],
    *,
    consented: set[str] | None = None,
) -> dict[str, Any]:
    """Add Leaderboard ``agent_refs`` on plaza-source rows.

    Builtin short ids (``pi@0.1.0``) skip Agent-org consent. Uploaded
    ``org/name@version`` still needs consent. ``file:`` / ``local/`` stay out.
    """
    if not is_plaza_source_suite(payload, official_ids):
        return payload
    refs = _agent_refs_from_overlay(
        payload.get("job_overlay") if isinstance(payload.get("job_overlay"), Mapping) else None
    )
    if consented is not None:
        refs = [
            row
            for row in refs
            if canonical_harness_id(str(row.get("package_id") or "")) is not None
            or str(row.get("package_id") or "") in consented
        ]
    if refs:
        payload["agent_refs"] = refs
    return payload


class RuntimeService:
    def __init__(self, inbox: Any, packages: Any, results: Any) -> None:
        self.inbox = inbox
        self.packages = packages
        self.results = results

    def performances_for_agent(self, package_id: str, auth: TokenInfo) -> list[dict[str, Any]]:
        """Performance rows for an uploaded ``org/name`` or a builtin short id."""
        want = (package_id or "").strip()
        if not want:
            return []
        harness = canonical_harness_id(want)
        if harness is not None:
            rows = self._reduce_builtin(harness, auth)
        else:
            rows = self._reduce(auth).get(want) or []
        return sorted(
            rows,
            key=lambda a: (
                str(a.get("agent_version") or ""),
                -float(a.get("created_at") or 0),
                str(a.get("role") or ""),
            ),
        )

    def collect_payload(self, package_id: str, auth: TokenInfo) -> dict[str, Any] | None:
        """Builtin collect setting. None for uploaded packs."""
        harness = canonical_harness_id((package_id or "").strip())
        if harness is None:
            return None
        stored = self.inbox.get_performance_collect_mode(harness)
        mode = stored if stored in COLLECT_MODES else DEFAULT_BUILTIN_COLLECT
        return {"mode": mode, "can_edit": auth_is_maintainer(auth)}

    def set_collect_mode(self, *, package_id: str, mode: str, auth: TokenInfo) -> dict[str, Any]:
        from services.registry.errors import RegistryAppError

        harness = canonical_harness_id((package_id or "").strip())
        if harness is None:
            raise RegistryAppError(
                "invalid_request",
                "performance collect is only for builtin agents",
                http_status=400,
            )
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "authentication required", http_status=401)
        if not auth_is_maintainer(auth):
            raise RegistryAppError("forbidden", "maintainer required", http_status=403)
        want = (mode or "").strip()
        if want not in COLLECT_MODES:
            raise RegistryAppError("invalid_request", "unknown collect mode", http_status=400)
        self.inbox.set_performance_collect_mode(
            package_id=harness, mode=want, updated_by=auth.user_id or ""
        )
        payload = self.collect_payload(harness, auth)
        assert payload is not None
        return payload

    def _collect_mode(self, harness_id: str) -> str:
        stored = self.inbox.get_performance_collect_mode(harness_id)
        if stored in COLLECT_MODES:
            return stored
        return DEFAULT_BUILTIN_COLLECT

    def _reduce_builtin(self, harness_id: str, auth: TokenInfo) -> list[dict[str, Any]]:
        official = official_dataset_ids(self.packages.list_releases(include_private=True))
        listed = self.results.list_suites(auth=auth, dataset_id=None)
        items = [s for s in (listed.get("items") or []) if isinstance(s, Mapping)]
        suite_ids = [str(s.get("suite_run_id") or "") for s in items]
        consents = self.inbox.list_agent_consents_for_suites(suite_ids)
        canonicals = self.inbox.list_canonical_models_for_suites(suite_ids)
        mode = self._collect_mode(harness_id)
        digest_cache: dict[tuple[str, str], str] = {}
        out: list[dict[str, Any]] = []
        for suite in items:
            if not is_public_complete_release(suite):
                continue
            sid = str(suite.get("suite_run_id") or "")
            official_src = is_plaza_source_suite(suite, official)
            personal_src = is_personal_source_suite(suite, official)
            auto = (mode == COLLECT_OFFICIAL and official_src) or (
                mode == COLLECT_OFFICIAL_AND_PERSONAL and (official_src or personal_src)
            )
            consented = harness_id in (consents.get(sid) or set())
            if not auto and not consented:
                continue
            package_digest = _package_digest_for_suite(self.packages, suite, digest_cache)
            rows = _performances_from_suite(
                suite,
                package_digest=package_digest,
                harness_id=harness_id,
            )
            stamped = [row for row in rows if _row_names_agent(row, harness_id)]
            if stamped:
                rows = stamped
            elif not auto:
                continue
            out.extend(_with_canonical_models(rows, canonicals.get(sid) or {}))
        return out

    def _reduce(self, auth: TokenInfo) -> dict[str, list[dict[str, Any]]]:
        official = official_dataset_ids(self.packages.list_releases(include_private=True))
        listed = self.results.list_suites(auth=auth, dataset_id=None)
        items = [s for s in (listed.get("items") or []) if isinstance(s, Mapping)]
        suite_ids = [str(s.get("suite_run_id") or "") for s in items]
        consents = self.inbox.list_agent_consents_for_suites(suite_ids)
        canonicals = self.inbox.list_canonical_models_for_suites(suite_ids)
        grouped: dict[str, list[dict[str, Any]]] = {}
        digest_cache: dict[tuple[str, str], str] = {}
        for suite in items:
            if not is_plaza_source_suite(suite, official):
                continue
            sid = str(suite.get("suite_run_id") or "")
            allowed = consents.get(sid) or set()
            package_digest = _package_digest_for_suite(self.packages, suite, digest_cache)
            for row in _with_canonical_models(
                _performances_from_suite(suite, package_digest=package_digest),
                canonicals.get(sid) or {},
            ):
                pid = str(row.get("package_id") or "")
                if not pid or pid not in allowed:
                    continue
                grouped.setdefault(pid, []).append(row)
        return grouped

    def detach_performance(
        self,
        *,
        package_id: str,
        suite_run_id: str,
        role: str,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        from services.registry.errors import RegistryAppError
        from services.registry.store import package_kind_for_media_type

        if not auth.user_id:
            raise RegistryAppError("unauthorized", "authentication required", http_status=401)
        want_role = (role or "").strip()
        sid = (suite_run_id or "").strip()
        agent_id = (package_id or "").strip()
        if not want_role or not sid or not agent_id:
            raise RegistryAppError(
                "invalid_request",
                "package, suite_run_id and role required",
                http_status=400,
            )
        harness = canonical_harness_id(agent_id)
        if harness is not None:
            if not auth_is_maintainer(auth):
                raise RegistryAppError("forbidden", "maintainer required", http_status=403)
            store_id = harness
        else:
            rows = self.packages.list_versions(agent_id, include_private=True)
            if not rows:
                raise RegistryAppError("not_found", "agent package not found", http_status=404)
            try:
                kind = package_kind_for_media_type(str(rows[0].media_type or ""))
            except ValueError as exc:
                raise RegistryAppError("invalid_request", str(exc), http_status=400) from exc
            if kind != "agent":
                raise RegistryAppError(
                    "invalid_request",
                    "performance detach is only for agents",
                    http_status=400,
                )
            org_id = (rows[0].org_id or "").strip()
            if not org_id or self.results.access.org_owner_status(org_id=org_id, auth=auth) != "ok":
                raise RegistryAppError("forbidden", "agent owner required", http_status=403)
            store_id = agent_id
        self.results.detach_agent_role(
            suite_run_id=sid,
            package_id=store_id,
            role=want_role,
        )
        return {"ok": True, "suite_run_id": sid, "role": want_role, "package_id": store_id}


def _row_names_agent(row: Mapping[str, Any], package_id: str) -> bool:
    parts = hub_agent_ref_parts(row.get("agent_ref"))
    if parts is None:
        return False
    named = parts[0]
    if named == package_id:
        return True
    hit = canonical_harness_id(named)
    return hit is not None and hit == package_id


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
        parts = hub_agent_ref_parts(raw.get("agent_ref"))
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
    packages: Any,
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
        release = packages.get_by_version(dataset_id, version)
    except Exception:  # noqa: BLE001 — performance stays YAML-only
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


def _version_from_ref(ref: object) -> str:
    if not isinstance(ref, str):
        return ""
    at = ref.find("@")
    if at <= 0:
        return ""
    rest = ref[at + 1 :]
    plus = rest.find("+")
    return (rest[:plus] if plus >= 0 else rest).strip()


def _performances_from_suite(
    suite: Mapping[str, Any],
    *,
    package_digest: str = "",
    harness_id: str | None = None,
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
        product = resolve_agent_id(raw)
        teammates_all.append(
            {
                "role": role_id,
                "executor": str(raw.get("executor") or "").strip(),
                "entry": product,
                "display_name": agent_display_name(raw),
            }
        )
        if harness_id is not None:
            if product != harness_id:
                continue
            published = published_agent_ref_parts(raw.get("agent_ref"))
            version = published[1] if published else _version_from_ref(raw.get("agent_ref"))
            valid.append((role_id, raw, (harness_id, version)))
            continue
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


def _with_canonical_models(
    rows: list[dict[str, Any]], stored: Mapping[str, str]
) -> list[dict[str, Any]]:
    if not stored:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        overlay = str(row.get("model") or "").strip()
        canonical = stored.get(overlay, "").strip()
        if canonical:
            row = {**row, "canonical_model": canonical}
        out.append(row)
    return out
