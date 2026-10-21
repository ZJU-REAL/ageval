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
from ageval.config.errors import ERROR_INVALID_OVERRIDE, ConfigError
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
        layout: str = "ageval",
    ) -> LockResult:
        """Lock one member and return the config plus its dataset context."""
        from ageval.application.host_env import load_host_env_files
        from ageval.config.harbor_layout import (
            LAYOUT_HARBOR,
            compute_harbor_eval_digest,
            open_harbor_root,
            require_layout,
            resolve_harbor_member,
        )
        from ageval.registry.digest import compute_eval_digest
        from ageval.registry.resolve import resolve_dataset_root_with_source

        layout = require_layout(layout)
        root, source = resolve_dataset_root_with_source(dataset_root, layout=layout)
        if layout == LAYOUT_HARBOR:
            if allow_prepare:
                raise ConfigError(
                    ERROR_INVALID_OVERRIDE,
                    "dataset prepare does not run for --layout harbor",
                    location="--allow-prepare",
                )
            opened = open_harbor_root(root)
            eval_digest = compute_harbor_eval_digest(root, opened)
            manifest = opened.manifest
            resolved = resolve_harbor_member(opened, task_id)
        else:
            # eval_digest is computed over the resolved tree before preparation:
            # prepare output is pinned transitively via the script content and
            # the assets manifest, so publish-time and run-time digests agree.
            # On later locks the marker replays the recorded digest, because
            # prepare output left on disk would otherwise drift the value.
            from ageval.config.prepare import prepare_dataset, stored_eval_digest

            eval_digest = stored_eval_digest(root) or compute_eval_digest(root)
            prepare_dataset(
                root,
                allow_prepare=allow_prepare,
                on_prepare_script=on_prepare_script,
                eval_digest=eval_digest,
            )
            manifest = load_dataset_manifest(root)
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
            layout=layout,
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
        layout: str = "ageval",
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
            layout=layout,
        ).summary()

    def tasks(self, dataset_root: Path | str, *, layout: str = "ageval") -> list[str]:
        from ageval.config.harbor_layout import LAYOUT_HARBOR, open_harbor_root, require_layout

        layout = require_layout(layout)
        root = Path(dataset_root).expanduser().resolve(strict=False)
        if layout == LAYOUT_HARBOR:
            return list(open_harbor_root(root).task_ids)
        return list_tasks(root)


def _parse_overrides(rows: Sequence[str]) -> dict[str, Any]:
    from ageval.config.overrides import parse_set_override

    out: dict[str, Any] = {}
    for row in rows:
        pointer, value = parse_set_override(row)
        out[pointer] = value
    return out
