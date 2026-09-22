"""Opened datasets for one `ageval view` process.

A dataset root or registry ref binds that one package. Any other directory is a
parent: immediate children whose ``ageval.yaml`` is ``ageval.dataset/1`` are
kept, and the rest are skipped. The directory name is the switch key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ageval.config.dataset import DATASET_FORMAT, list_tasks, load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.registry.ref import parse_package_ref
from ageval.registry.resolve import resolve_dataset_root


@dataclass(frozen=True, slots=True)
class OpenedDataset:
    """One dataset directory bound into this viewer."""

    key: str
    root: Path
    dataset_id: str
    version: str
    description: str | None
    task_count: int

    @property
    def label(self) -> str:
        return f"{self.dataset_id}@{self.version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "description": self.description,
            "task_count": self.task_count,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class ViewSession:
    """Datasets opened by this process. `parent` is set only for a directory scan."""

    datasets: tuple[OpenedDataset, ...]
    parent: Path | None
    mode: str

    @property
    def landing(self) -> str:
        """More than one dataset lands on the list. Exactly one lands on Jobs."""
        return "jobs" if len(self.datasets) == 1 else "datasets"

    def by_key(self, key: str | None) -> OpenedDataset:
        if key:
            for item in self.datasets:
                if item.key == key:
                    return item
            raise ConfigError(
                "unknown_dataset",
                f"unknown dataset {key}",
                location="dataset",
            )
        if len(self.datasets) == 1:
            return self.datasets[0]
        if not self.datasets:
            raise ConfigError(
                "unknown_dataset",
                "no dataset is open",
                location="dataset",
            )
        raise ConfigError(
            "dataset_required",
            "dataset query required when more than one dataset is open",
            location="dataset",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": self.mode,
            "landing": self.landing,
            "dataset_count": len(self.datasets),
            "datasets": [item.as_dict() for item in self.datasets],
        }


def open_view(raw: str | Path) -> ViewSession:
    """Bind one dataset, or the dataset children of a parent directory."""
    ref = parse_package_ref(raw)
    if ref.kind != "path":
        root = resolve_dataset_root(raw)
        return ViewSession(
            datasets=(_bind(root, strict_tasks=True),),
            parent=None,
            mode="dataset",
        )
    assert ref.path is not None
    path = ref.path
    if _is_dataset_root(path):
        return ViewSession(
            datasets=(_bind(path, strict_tasks=True),),
            parent=None,
            mode="dataset",
        )
    found: list[OpenedDataset] = []
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ConfigError(
            "invalid_package",
            f"cannot read directory: {exc}",
            location=str(path),
        ) from exc
    for child in children:
        if not child.is_dir() or not _is_dataset_root(child):
            continue
        try:
            found.append(_bind(child, strict_tasks=False))
        except ConfigError:
            continue
    return ViewSession(datasets=tuple(found), parent=path, mode="parent")


def _is_dataset_root(root: Path) -> bool:
    return _format_of(root) == DATASET_FORMAT


def _format_of(root: Path) -> str | None:
    path = root / "ageval.yaml"
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    fmt = raw.get("format")
    return fmt if isinstance(fmt, str) else None


def _bind(root: Path, *, strict_tasks: bool) -> OpenedDataset:
    manifest = load_dataset_manifest(root)
    if strict_tasks:
        task_count = len(list_tasks(root, manifest=manifest))
    else:
        try:
            task_count = len(list_tasks(root, manifest=manifest))
        except ConfigError:
            task_count = 0
    key = root.name
    if not key or key in {".", ".."} or "/" in key or "\\" in key:
        raise ConfigError(
            "invalid_package",
            f"dataset directory name cannot be a switch key: {key!r}",
            location=str(root),
        )
    return OpenedDataset(
        key=key,
        root=root.resolve(strict=False),
        dataset_id=manifest.dataset_id,
        version=manifest.version,
        description=manifest.description,
        task_count=task_count,
    )
