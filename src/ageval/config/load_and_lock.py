"""Config Core façade: load, merge, validate, canonicalize, digest, freeze.

This module is the only normative reader of a member ``task.yaml``. It never
imports or executes package-local Python and never starts an Attempt.

What the task ships decides what runs: ``run.py``, ``evaluator.py``,
``environment/Dockerfile`` and ``environment/setup.sh`` are picked up by
presence, so a minimal ``task.yaml`` is two lines plus the fields that really
vary.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.config.capabilities import CapabilityCatalog
from ageval.config.constants import DEFAULTS
from ageval.config.digest import digest_payload
from ageval.config.errors import (
    ERROR_INVALID_PACKAGE,
    ERROR_INVALID_SCHEMA,
    ConfigError,
)
from ageval.config.model import (
    LockedTaskConfig,
    ResolutionEntry,
    ResolutionRecord,
    freeze,
)
from ageval.config.overrides import apply_json_pointer, is_allowlisted_override_pointer
from ageval.config.ports import PackageReader
from ageval.config.profiles import (
    JobDocument,
    apply_profile_override,
    assert_slots_have_no_inline_binding,
    is_profile_override_pointer,
    merge_job_onto_slots,
    project_job_overlay,
)
from ageval.config.provenance import merge_provenance, validate_provenance
from ageval.config.validate import (
    collect_resolved_references,
    validate_document,
    validate_top_level_layout,
)
from ageval.config.yaml_io import parse_yaml
from ageval.plugins.slots import ENVIRONMENT


class ConfigCore:
    """Normative Config Core façade."""

    def __init__(self, package_reader: PackageReader) -> None:
        self._reader = package_reader

    def load_and_lock(
        self,
        task_root: Path,
        task_id: str,
        *,
        dataset_id: str,
        dataset_version: str,
        job: JobDocument,
        selected_profile: str | None = None,
        overrides: Mapping[str, object] | None = None,
        capabilities: CapabilityCatalog,
        dataset_provenance: Mapping[str, object] | None = None,
        force_build: bool = False,
    ) -> LockedTaskConfig:
        """Read, merge, validate, canonicalize, digest, and freeze one task.

        Parameters
        ----------
        task_root:
            Member task directory (contains ``task.yaml``).
        task_id:
            Must equal ``task.yaml`` ``task_id``.
        job:
            Dataset-root job document: the ``environment`` winner plus the agent
            profiles that bind the role slots this task declares.
        selected_profile:
            ``--profile`` key: bind every declared role to that profile.
        overrides:
            JSON Pointer → value. ``/agent_profiles/<role>/…`` pointers apply to
            the job document before the slot merge; the rest are parameter leaves.
        """
        root = self._resolve_root(task_root)
        validate_top_level_layout(self._reader, root)
        self._validate_dataset_shared(root)

        raw = self._read_task_document(root)
        resolution: list[ResolutionEntry] = [
            ResolutionEntry(source="task.yaml", pointer="/", note="task document"),
        ]
        merged = self._apply_defaults(raw, resolution)

        job_doc = copy.deepcopy(job)
        param_overrides = self._split_overrides(overrides, job_doc, resolution)

        slots_raw = merged.get("agent_profiles") or []
        if not isinstance(slots_raw, list):
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "agent_profiles must be a list", location="/agent_profiles"
            )
        assert_slots_have_no_inline_binding(slots_raw)
        if slots_raw:
            self._expand_profile_env_refs(job_doc)
            self._assert_overlays(job_doc, task_root=root)
            merged["agent_profiles"] = merge_job_onto_slots(
                slots_raw, job_doc, selected_profile=selected_profile
            )
            resolution.append(
                ResolutionEntry(
                    source="profiles.yaml",
                    pointer="/agent_profiles",
                    note="job agent profiles bound onto role slots",
                )
            )
        else:
            merged["agent_profiles"] = []

        for pointer, value in param_overrides.items():
            apply_json_pointer(merged, pointer, value)
            resolution.append(
                ResolutionEntry(source="cli-override", pointer=pointer, note="explicit override")
            )

        validate_document(
            self._reader,
            merged,
            task_id=task_id,
            root=root,
            capabilities=capabilities,
        )
        resolved_refs = collect_resolved_references(self._reader, merged, root)
        _apply_evaluate_job(job_doc, resolved_refs)
        resolution.append(
            ResolutionEntry(
                source="package-files",
                pointer="/resolved_references",
                note="entrypoints and recipes recognized from shipped files",
            )
        )

        provenance = self._effective_provenance(merged, dataset_provenance, resolution)
        profiles_rows = list(merged["agent_profiles"])
        role_ids = [str(row.get("id")) for row in profiles_rows if row.get("id") is not None]
        job_overlay = project_job_overlay(
            {rid: row for rid, row in ((str(r.get("id")), r) for r in profiles_rows)},
            environment=job_doc.environment,
            environment_options=job_doc.environment_options,
            evaluate_host=job_doc.evaluate_host,
            role_ids=role_ids,
        )
        extension_bindings = self._resolve_extension_bindings(
            profiles_rows,
            environment=job_doc.environment,
            requires=_required_capabilities(merged.get("requires") or {}, resolved_refs),
            environment_options=job_doc.environment_options,
        )
        if extension_bindings:
            resolution.append(
                ResolutionEntry(
                    source="extension_registry",
                    pointer="/extension_bindings",
                    note="resolved exclusive winners, chains, services and inject",
                )
            )

        fields: dict[str, Any] = {
            "format": str(merged["format"]),
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "task_id": str(merged["task_id"]),
            "environment": job_doc.environment,
            "profile": selected_profile,
            "agent_profiles": tuple(freeze(row) for row in profiles_rows),
            "parameters": freeze(merged.get("parameters") or {}),
            "requires": freeze(merged.get("requires") or {}),
            "limits": freeze(merged["limits"]),
            "artifacts": freeze(merged["artifacts"]),
            "evaluation": freeze(merged["evaluation"]),
            "resolution": ResolutionRecord(entries=tuple(resolution)),
            "resolved_references": freeze(resolved_refs),
            "provenance": freeze(provenance) if provenance is not None else None,
            "job_overlay": freeze(job_overlay),
            "extension_bindings": freeze(extension_bindings) if extension_bindings else None,
            "force_build": force_build,
        }
        provisional = LockedTaskConfig(digest="", **fields)
        return LockedTaskConfig(digest=digest_payload(provisional.canonical_payload()), **fields)

    # --- steps ---------------------------------------------------------------

    def _resolve_root(self, task_root: Path) -> Path:
        try:
            return self._reader.resolve_root(task_root)
        except (OSError, FileNotFoundError) as exc:
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                f"cannot open task root: {task_root}",
                location=str(task_root),
            ) from exc

    def _validate_dataset_shared(self, root: Path) -> None:
        from ageval.config.dataset import load_dataset_manifest
        from ageval.config.shared import infer_dataset_root_from_task, validate_shared_layout

        dataset_root = infer_dataset_root_from_task(root)
        if dataset_root is None:
            return
        manifest = load_dataset_manifest(dataset_root)
        validate_shared_layout(dataset_root, tasks_root=manifest.tasks_root)

    def _read_task_document(self, root: Path) -> dict[str, Any]:
        from ageval.config.checks import reject_env_interpolation

        if not self._reader.exists(root, "task.yaml"):
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                "task.yaml not found",
                location="task.yaml",
            )
        try:
            text = self._reader.read_text(root, "task.yaml")
        except (OSError, ValueError) as exc:
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                f"cannot read task.yaml: {exc}",
                location="task.yaml",
            ) from exc
        reject_env_interpolation(text, what="task.yaml", location="task.yaml")
        return parse_yaml(text)

    @staticmethod
    def _apply_defaults(
        raw: dict[str, Any],
        resolution: list[ResolutionEntry],
    ) -> dict[str, Any]:
        merged = copy.deepcopy(raw)
        for key, default_value in DEFAULTS.items():
            if merged.get(key) is None:
                merged[key] = copy.deepcopy(default_value)
                resolution.append(
                    ResolutionEntry(source="default", pointer=f"/{key}", note="explicit default")
                )
            elif isinstance(default_value, dict) and isinstance(merged.get(key), dict):
                for d_key, d_val in default_value.items():
                    if d_key not in merged[key]:
                        merged[key][d_key] = copy.deepcopy(d_val)
                        resolution.append(
                            ResolutionEntry(
                                source="default",
                                pointer=f"/{key}/{d_key}",
                                note="explicit default",
                            )
                        )
        return merged

    @staticmethod
    def _split_overrides(
        overrides: Mapping[str, object] | None,
        job: JobDocument,
        resolution: list[ResolutionEntry],
    ) -> dict[str, object]:
        """Job axis overrides go to the job document; the rest stay parameters."""
        param_overrides: dict[str, object] = {}
        for pointer, value in (overrides or {}).items():
            pointer_s = str(pointer)
            if not is_allowlisted_override_pointer(pointer_s):
                from ageval.config.errors import ERROR_INVALID_OVERRIDE

                raise ConfigError(
                    ERROR_INVALID_OVERRIDE,
                    f"pointer not allowlisted for override: {pointer_s}",
                    location=pointer_s,
                )
            if is_profile_override_pointer(pointer_s):
                apply_profile_override(job, pointer_s, value)
                resolution.append(
                    ResolutionEntry(
                        source="cli-override",
                        pointer=pointer_s,
                        note="job profile override",
                    )
                )
            else:
                param_overrides[pointer_s] = value
        return param_overrides

    @staticmethod
    def _assert_overlays(job: JobDocument, *, task_root: Path) -> None:
        """A declared overlay must exist and must not carry a secret.

        Checked at lock time, because a run that discovers a missing overlay
        halfway through has already started a box for nothing.
        """
        from ageval.config.overlay_files import assert_overlays_at_lock, overlay_root_for_binding
        from ageval.config.shared import infer_dataset_root_from_task

        dataset_root = infer_dataset_root_from_task(task_root)
        for role_id, row in job.profiles.items():
            assert_overlays_at_lock(
                overlay_root_for_binding(row, dataset_root),
                row,
                location=f"/agent_profiles/{role_id}/overlays",
            )

    @staticmethod
    def _expand_profile_env_refs(job: JobDocument) -> None:
        from ageval.config.env_refs import expand_profile_env_refs

        for role_id, row in job.profiles.items():
            expand_profile_env_refs(row, location=f"/agent_profiles/{role_id}")

    @staticmethod
    def _effective_provenance(
        merged: dict[str, Any],
        dataset_provenance: Mapping[str, object] | None,
        resolution: list[ResolutionEntry],
    ) -> dict[str, Any] | None:
        task_prov_raw = merged.get("provenance")
        task_prov: dict[str, Any] | None = None
        if task_prov_raw is not None:
            task_prov = validate_provenance(task_prov_raw, location="/provenance")
            resolution.append(
                ResolutionEntry(source="task.yaml", pointer="/provenance", note="task provenance")
            )
        dataset_prov: dict[str, Any] | None = None
        if dataset_provenance is not None:
            dataset_prov = validate_provenance(
                dict(dataset_provenance), location="dataset:/provenance"
            )
            if task_prov is None:
                resolution.append(
                    ResolutionEntry(
                        source="dataset",
                        pointer="/provenance",
                        note="dataset default provenance",
                    )
                )
        return merge_provenance(dataset=dataset_prov, task=task_prov)

    @staticmethod
    def _resolve_extension_bindings(
        profiles_rows: Sequence[Mapping[str, Any]],
        *,
        environment: str,
        requires: Mapping[str, Any],
        environment_options: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]] | None:
        """Resolve the slot / service / inject graph per profile. Fails closed.

        A task with no role slot still gets one resolve: it needs a box, and the
        capabilities it requires must be checked before anything starts.
        """
        from ageval.plugins.bootstrap import ensure_bootstrapped
        from ageval.plugins.errors import ExtensionRegistryError
        from ageval.plugins.lock_bind import extension_graph_to_lock
        from ageval.plugins.plugin_requires import PluginRequiresError
        from ageval.plugins.protocol import intent_from_profile
        from ageval.plugins.resolve import resolve as resolve_extensions

        try:
            registry = ensure_bootstrapped()
        except PluginRequiresError as exc:
            raise ConfigError(exc.kind, str(exc), location="/agent_profiles") from exc
        out: dict[str, dict[str, Any]] = {}
        rows = list(profiles_rows) or [{}]
        for profile in rows:
            pid = str(profile.get("id") or "").strip()
            intent = intent_from_profile(
                profile,
                environment=environment,
                environment_options=environment_options,
                requires=requires,
            )
            intent.profile_id = pid
            try:
                graph = resolve_extensions(intent, registry, materialize=True)
            except ExtensionRegistryError as exc:
                where = f"/agent_profiles/{pid}/extension_bindings" if pid else "/requires"
                raise ConfigError(
                    ERROR_INVALID_SCHEMA,
                    f"extension resolve failed for profile {pid!r}: {exc}"
                    if pid
                    else f"the box this job selected cannot run this task: {exc}",
                    location=where,
                ) from exc
            out[pid] = extension_graph_to_lock(graph)
        return out or None


_ISOLATED_EVALUATE_KINDS = frozenset({"docker"})
_EGRESS_KINDS = frozenset({"docker"})


def _apply_evaluate_job(job: JobDocument, resolved_refs: dict[str, Any]) -> None:
    """Fail closed on isolated / egress; ignore evaluate recipes when omitted."""
    isolated = bool(job.evaluate_host.get("isolated"))
    named = resolved_refs.get("evaluation_environments")
    if named:
        if not isolated:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation.environments requires evaluate_host.isolated",
                location="/evaluate_host",
            )
        if job.environment not in _ISOLATED_EVALUATE_KINDS:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation.environments requires environment: docker",
                location="/evaluate_host",
            )
        resolved_refs.pop("environment_evaluate_dockerfile", None)
        resolved_refs.pop("evaluation_docker_image", None)
    elif not isolated:
        resolved_refs.pop("environment_evaluate_dockerfile", None)
        resolved_refs.pop("evaluation_docker_image", None)
        resolved_refs.pop("evaluation_environments", None)
    else:
        if job.environment not in _ISOLATED_EVALUATE_KINDS:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluate_host.isolated requires environment: docker",
                location="/evaluate_host",
            )
        has_recipe = bool(resolved_refs.get("environment_evaluate_dockerfile")) or bool(
            resolved_refs.get("evaluation_docker_image")
        )
        if not has_recipe:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluate_host.isolated requires environment/evaluate.Dockerfile "
                "or evaluation.docker_image",
                location="/evaluate_host",
            )
    _require_docker_egress_keys(
        job.environment,
        job.environment_options,
        location="/environment_options",
    )
    scoring_options = job.evaluate_host.get("environment_options")
    if not scoring_options:
        return
    if not isolated:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluate_host.environment_options requires evaluate_host.isolated: true",
            location="/evaluate_host/environment_options",
        )
    _require_docker_egress_keys(
        job.environment,
        scoring_options,
        location="/evaluate_host/environment_options",
    )


def _require_docker_egress_keys(kind: str, options: Mapping[str, Any], *, location: str) -> None:
    for key in ("egress", "egress_allow"):
        if key not in options:
            continue
        if kind in _EGRESS_KINDS:
            continue
        pointer = f"{location}/{key}"
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"{pointer.lstrip('/').replace('/', '.')} requires environment: docker",
            location=pointer,
        )


def _required_capabilities(
    requires: Mapping[str, Any],
    resolved_refs: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Capabilities the box must deliver, from the task and from what it ships.

    A task that ships ``environment/compose.yaml`` needs ``compose`` whether or
    not it said so, and a kind that cannot compose must fail the lock rather
    than start a box it cannot finish.
    """
    wanted: dict[str, list[str]] = {}
    for service, names in requires.items():
        if isinstance(names, (list, tuple)):
            wanted[str(service)] = [str(name) for name in names]
    if resolved_refs.get("environment_compose"):
        box = wanted.setdefault(ENVIRONMENT, [])
        if "compose" not in box:
            box.append("compose")
    return {service: tuple(names) for service, names in wanted.items()}
