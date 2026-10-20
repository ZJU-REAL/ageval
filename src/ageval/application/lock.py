"""Public ``ageval lock`` use case: resolve one dataset member and lock it."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.config.capabilities import CapabilityCatalog
from ageval.config.dataset import (
    DatasetManifest,
    ResolvedTask,
    list_tasks,
    load_dataset_manifest,
    resolve_task,
)
from ageval.config.load_and_lock import ConfigCore
from ageval.config.model import LockedTaskConfig, locked_to_summary
from ageval.config.profiles import JobDocument, resolve_job_document


@dataclass(frozen=True, slots=True)
class LockResult:
    """Locked config plus what the caller needs to open an Attempt."""

    lock: LockedTaskConfig
    resolved: ResolvedTask
    manifest: DatasetManifest
    job: JobDocument
    source: dict[str, str] | None = None
    eval_digest: str | None = None

    def summary(self) -> dict[str, Any]:
        out = locked_to_summary(self.lock).as_dict()
        if self.source:
            out["source"] = dict(self.source)
        if self.eval_digest:
            out["eval_digest"] = self.eval_digest
        return out


class LockCommand:
    """Read a dataset root, resolve a member, and produce its locked config."""

    def __init__(self, *, config_core: ConfigCore, capabilities: CapabilityCatalog) -> None:
        self._config = config_core
        self._capabilities = capabilities

    def lock(
        self,
        dataset_root: Path | str,
        task_id: str,
        *,
        profile: str | None = None,
        profiles_path: Path | str | None = None,
        set_overrides: Sequence[str] = (),
        overrides: dict[str, Any] | None = None,
        force_build: bool = False,
        allow_prepare: bool = False,
        on_prepare_script: Callable[[str, str], None] | None = None,
    ) -> LockResult:
        """Lock one member and return the config plus its dataset context."""
        from ageval.application.host_env import load_host_env_files
        from ageval.registry.digest import compute_eval_digest
        from ageval.registry.resolve import resolve_dataset_root_with_source

        root, source = resolve_dataset_root_with_source(dataset_root)
        # Dataset preparation (assets + gated prepare script) completes
        # before the manifest/digest are read and any Attempt can open.
        from ageval.config.prepare import prepare_dataset

        prepare_dataset(root, allow_prepare=allow_prepare, on_prepare_script=on_prepare_script)
        manifest = load_dataset_manifest(root)
        eval_digest = compute_eval_digest(root)
        resolved = resolve_task(root, task_id, manifest=manifest)
        # Host credential locators from the dataset-root .env (values never
        # enter the lock or evidence).
        load_host_env_files(package_root=root)
        job = resolve_job_document(root, profiles_path=profiles_path)
        merged_overrides = dict(overrides or {})
        merged_overrides.update(_parse_overrides(set_overrides))
        lock = self._config.load_and_lock(
            resolved.task_dir,
            resolved.task_id,
            dataset_id=manifest.dataset_id,
            dataset_version=manifest.version,
            job=job,
            selected_profile=profile,
            overrides=merged_overrides or None,
            capabilities=self._capabilities,
            dataset_provenance=manifest.provenance,
            force_build=force_build,
        )
        return LockResult(
            lock=lock,
            resolved=resolved,
            manifest=manifest,
            job=job,
            source=source,
            eval_digest=eval_digest,
        )

    def run(
        self,
        *,
        dataset_root: Path | str,
        task_id: str,
        set_overrides: Sequence[str] = (),
        profiles_path: Path | str | None = None,
        profile: str | None = None,
        allow_prepare: bool = False,
        on_prepare_script: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """CLI-facing form: return the deterministic lock summary document."""
        return self.lock(
            dataset_root,
            task_id,
            profile=profile,
            profiles_path=profiles_path,
            set_overrides=set_overrides,
            allow_prepare=allow_prepare,
            on_prepare_script=on_prepare_script,
        ).summary()

    def tasks(self, dataset_root: Path | str) -> list[str]:
        root = Path(dataset_root).expanduser().resolve(strict=False)
        return list_tasks(root)


def _parse_overrides(rows: Sequence[str]) -> dict[str, Any]:
    from ageval.config.overrides import parse_set_override

    out: dict[str, Any] = {}
    for row in rows:
        pointer, value = parse_set_override(row)
        out[pointer] = value
    return out
