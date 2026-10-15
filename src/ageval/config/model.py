"""Immutable Config models and lock summary view.

All nested structures returned from ``load_and_lock`` are recursively frozen
(mapping → MappingProxyType, list → tuple) so consumers cannot mutate Trial
truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def freeze(value: Any) -> Any:
    """Recursively freeze mappings and sequences for immutability."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Deep-copy a frozen structure into plain dict/list for canonicalization."""
    if isinstance(value, Mapping):
        return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ResolutionEntry:
    """One effective value source in merge order."""

    source: str
    pointer: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionRecord:
    """Ordered record of how the locked config was assembled."""

    entries: tuple[ResolutionEntry, ...] = ()

    def as_plain(self) -> list[dict[str, str]]:
        return [
            {"source": e.source, "pointer": e.pointer, **({"note": e.note} if e.note else {})}
            for e in self.entries
        ]


@dataclass(frozen=True, slots=True)
class LockedTaskConfig:
    """Immutable locked task configuration — Trial configuration truth."""

    format: str
    dataset_id: str
    dataset_version: str
    task_id: str
    # Exclusive slot winner ids resolved for this Trial.
    environment: str
    profile: str | None
    agent_profiles: tuple[Mapping[str, Any], ...]
    parameters: Mapping[str, Any]
    requires: Mapping[str, Any]
    limits: Mapping[str, Any]
    artifacts: Mapping[str, Any]
    evaluation: Mapping[str, Any]
    resolution: ResolutionRecord
    digest: str
    # Package-relative resolved references (entrypoints, recipes, artifact paths).
    resolved_references: Mapping[str, Any] = field(default_factory=lambda: freeze({}))
    # Optional package provenance (溯源); observational — never Attempt PASS.
    provenance: Mapping[str, Any] | None = None
    # Secret-free job document used for this lock; not task identity.
    job_overlay: Mapping[str, Any] | None = None
    # Per-profile resolved slot / service / inject graph.
    extension_bindings: Mapping[str, Any] | None = None
    # Set when the operator asked to rebuild the box recipe.
    force_build: bool = False
    # Home-file ACP rows a profile referenced. Omitted when every entry is packaged.
    acp_user_entries: Mapping[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        """Payload used for digest: everything except the digest field itself."""
        payload: dict[str, Any] = {
            "format": self.format,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "task_id": self.task_id,
            "environment": self.environment,
            "profile": self.profile,
            "agent_profiles": thaw(self.agent_profiles),
            "parameters": thaw(self.parameters),
            "requires": thaw(self.requires),
            "limits": thaw(self.limits),
            "artifacts": thaw(self.artifacts),
            "evaluation": thaw(self.evaluation),
            "resolution": self.resolution.as_plain(),
            "resolved_references": thaw(self.resolved_references),
        }
        if self.provenance is not None:
            payload["provenance"] = thaw(self.provenance)
        if self.job_overlay is not None:
            payload["job_overlay"] = thaw(self.job_overlay)
        if self.extension_bindings is not None:
            payload["extension_bindings"] = thaw(self.extension_bindings)
        if self.acp_user_entries is not None:
            payload["acp_user_entries"] = thaw(self.acp_user_entries)
        return payload

    def profile_row(self, profile_id: str) -> Mapping[str, Any] | None:
        for row in self.agent_profiles:
            if str(row.get("id")) == profile_id:
                return row
        return None


@dataclass(frozen=True, slots=True)
class LockSummary:
    """Deterministic CLI stdout view (no secrets, no host absolute paths)."""

    format: str
    dataset_id: str
    dataset_version: str
    task_id: str
    environment: str
    resolved_references: Mapping[str, Any]
    resolution: Sequence[Mapping[str, str]]
    digest: str
    profile: str | None = None
    provenance: Mapping[str, Any] | None = None
    job_overlay: Mapping[str, Any] | None = None
    extension_bindings: Mapping[str, Any] | None = None
    acp_user_entries: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "digest": self.digest,
            "environment": self.environment,
            "format": self.format,
            "resolution": thaw(list(self.resolution)),
            "resolved_references": thaw(self.resolved_references),
            "task_id": self.task_id,
        }
        if self.profile is not None:
            out["profile"] = self.profile
        if self.provenance is not None:
            out["provenance"] = thaw(self.provenance)
        if self.job_overlay is not None:
            out["job_overlay"] = thaw(self.job_overlay)
        if self.extension_bindings is not None:
            out["extension_bindings"] = thaw(self.extension_bindings)
        if self.acp_user_entries is not None:
            out["acp_user_entries"] = thaw(self.acp_user_entries)
        return out


def locked_to_summary(lock: LockedTaskConfig) -> LockSummary:
    """Project a LockedTaskConfig into the public lock summary."""
    return LockSummary(
        format=lock.format,
        dataset_id=lock.dataset_id,
        dataset_version=lock.dataset_version,
        task_id=lock.task_id,
        environment=lock.environment,
        resolved_references=lock.resolved_references,
        resolution=tuple(freeze(e) for e in lock.resolution.as_plain()),
        digest=lock.digest,
        profile=lock.profile,
        provenance=lock.provenance,
        job_overlay=lock.job_overlay,
        extension_bindings=lock.extension_bindings,
        acp_user_entries=lock.acp_user_entries,
    )
