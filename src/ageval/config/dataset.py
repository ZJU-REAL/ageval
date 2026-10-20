"""Dataset manifest load, member enumeration, and task resolve.

Delivery unit is a dataset root with ``ageval.yaml`` (``ageval.dataset/1``).
Each member lives under ``tasks/<task_id>/task.yaml`` (``ageval.task/1``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ageval.config.errors import (
    ERROR_INVALID_FORMAT,
    ERROR_INVALID_PACKAGE,
    ERROR_INVALID_SCHEMA,
    ERROR_UNKNOWN_TASK,
    ConfigError,
)

DATASET_FORMAT = "ageval.dataset/1"
TASK_CONFIG_FILENAME = "task.yaml"
DEFAULT_TASKS_ROOT = "tasks"

# dataset_id charset (case-sensitive; prefer lowercase). See docs/design/02.
_DATASET_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9._/-]*[a-z0-9])?$")

# Task fields belong to a member ``task.yaml``, never to the dataset root.
_FORBIDDEN_DATASET_ROOT_KEYS = frozenset(
    {
        "task_id",
        "parameters",
        "agent_profiles",
        "environment",
        "requires",
        "limits",
        "artifacts",
        "evaluation",
    }
)


_DEFAULTS_ALLOWLIST = frozenset({"max_concurrent_tasks"})


@dataclass(frozen=True, slots=True)
class DatasetDefaults:
    """Optional dataset-level defaults consumed only by suite scheduling."""

    max_concurrent_tasks: int | None = None


@dataclass(frozen=True, slots=True)
class DatasetAsset:
    """One declarative downloadable asset (path + url + pinned sha256)."""

    path: str
    url: str
    sha256: str


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSET_URL_PREFIXES = ("https://", "http://", "file://")


def _validate_asset_relpath(value: object, *, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "asset path must be a non-empty string", location=location
        )
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("/") or ".." in Path(text).parts or not text:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "asset path must be relative to the dataset root without '..'",
            location=location,
        )
    return text


def _parse_assets(raw: object) -> tuple[DatasetAsset, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(ERROR_INVALID_SCHEMA, "assets must be a list", location="/assets")
    out: list[DatasetAsset] = []
    for i, item in enumerate(raw):
        loc = f"/assets/{i}"
        if not isinstance(item, dict):
            raise ConfigError(ERROR_INVALID_SCHEMA, "asset must be a mapping", location=loc)
        unknown = set(item) - {"path", "url", "sha256"}
        if unknown:
            raise ConfigError(
                ERROR_INVALID_SCHEMA, f"unknown asset keys: {sorted(unknown)}", location=loc
            )
        path = _validate_asset_relpath(item.get("path"), location=f"{loc}/path")
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith(_ASSET_URL_PREFIXES):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "asset url must start with https://, http:// or file://",
                location=f"{loc}/url",
            )
        sha = item.get("sha256")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "asset sha256 must be 64 lowercase hex characters",
                location=f"{loc}/sha256",
            )
        out.append(DatasetAsset(path=path, url=url, sha256=sha))
    return tuple(out)


def _parse_prepare(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "prepare must be a non-empty string", location="/prepare"
        )
    text = raw.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("/") or ".." in Path(text).parts or not text:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "prepare must be relative to the dataset root without '..'",
            location="/prepare",
        )
    return text


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Immutable dataset root document (``ageval.dataset/1``)."""

    format: str
    dataset_id: str
    version: str
    tasks_root: str
    description: str | None = None
    defaults: DatasetDefaults | None = None
    # Optional dataset-wide provenance; member task.yaml may fully override.
    provenance: dict[str, object] | None = None
    assets: tuple[DatasetAsset, ...] = ()
    prepare: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedTask:
    """Local resolve result: dataset root + member task directory."""

    dataset_root: Path
    task_id: str
    task_dir: Path
    task_config_path: Path
    dataset_id: str
    dataset_version: str


def validate_dataset_id(dataset_id: str) -> None:
    """Fail closed if *dataset_id* violates frozen charset rules (design/02)."""
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id must be a non-empty string",
            location="/dataset_id",
        )
    if len(dataset_id) > 128:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id length must be 1–128",
            location="/dataset_id",
        )
    if ".." in dataset_id or "//" in dataset_id:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id must not contain '..' or '//'",
            location="/dataset_id",
        )
    if dataset_id.startswith("/") or dataset_id.endswith("/"):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id must not start or end with '/'",
            location="/dataset_id",
        )
    if not _DATASET_ID_RE.fullmatch(dataset_id):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id charset invalid (expected ^[a-z0-9]([a-z0-9._/-]*[a-z0-9])?$)",
            location="/dataset_id",
        )


def _parse_yaml_mapping(text: str, *, location: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"invalid YAML: {exc}",
            location=location,
        ) from exc
    if data is None:
        raise ConfigError(ERROR_INVALID_SCHEMA, "empty document", location=location)
    if not isinstance(data, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "document root must be a mapping",
            location=location,
        )
    return data


def load_dataset_manifest(dataset_root: Path) -> DatasetManifest:
    """Load and validate dataset ``ageval.yaml`` from *dataset_root*."""
    root = dataset_root.expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"dataset root is not a directory: {dataset_root}",
            location=str(dataset_root),
        )
    path = root / "ageval.yaml"
    if not path.is_file():
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            "ageval.yaml not found at dataset root",
            location="ageval.yaml",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"cannot read ageval.yaml: {exc}",
            location="ageval.yaml",
        ) from exc

    from ageval.config.checks import reject_env_interpolation

    reject_env_interpolation(text, what="ageval.yaml", location="ageval.yaml")

    raw = _parse_yaml_mapping(text, location="ageval.yaml")
    return _manifest_from_mapping(raw)


def _manifest_from_mapping(raw: dict[str, Any]) -> DatasetManifest:
    fmt = raw.get("format")
    if not isinstance(fmt, str) or not fmt:
        raise ConfigError(
            ERROR_INVALID_FORMAT,
            "missing or invalid format",
            location="/format",
        )
    if fmt != DATASET_FORMAT:
        # Common mistake: pointing CLI at a task member (task schema).
        if fmt == "ageval.task/1":
            raise ConfigError(
                ERROR_INVALID_FORMAT,
                "expected ageval.dataset/1 at dataset root; got ageval.task/1 "
                "(pass the dataset root, not a task member directory)",
                location="/format",
            )
        raise ConfigError(
            ERROR_INVALID_FORMAT,
            f"unsupported dataset format: {fmt}",
            location="/format",
        )

    for forbidden in _FORBIDDEN_DATASET_ROOT_KEYS:
        if forbidden in raw:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"dataset root must not declare task field {forbidden!r}",
                location=f"/{forbidden}",
            )

    dataset_id = raw.get("dataset_id")
    if not isinstance(dataset_id, str):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "dataset_id required",
            location="/dataset_id",
        )
    validate_dataset_id(dataset_id)

    version = raw.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "version must be a non-empty string",
            location="/version",
        )

    tasks_block = raw.get("tasks")
    tasks_root = DEFAULT_TASKS_ROOT
    if tasks_block is not None:
        if not isinstance(tasks_block, dict):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "tasks must be a mapping",
                location="/tasks",
            )
        root_val = tasks_block.get("root", DEFAULT_TASKS_ROOT)
        if not isinstance(root_val, str) or not root_val.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "tasks.root must be a non-empty string",
                location="/tasks/root",
            )
        tasks_root = root_val.strip().replace("\\", "/").strip("/")
        if not tasks_root or ".." in Path(tasks_root).parts or tasks_root.startswith("/"):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "tasks.root must be a relative path without '..'",
                location="/tasks/root",
            )
        unknown_tasks_keys = set(tasks_block) - {"root"}
        if unknown_tasks_keys:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"unknown tasks keys: {sorted(unknown_tasks_keys)}",
                location="/tasks",
            )

    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "description must be a string when set",
            location="/description",
        )

    defaults_obj: DatasetDefaults | None = None
    defaults_raw = raw.get("defaults")
    if defaults_raw is not None:
        if not isinstance(defaults_raw, dict):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "defaults must be a mapping",
                location="/defaults",
            )
        unknown_defaults = set(defaults_raw) - _DEFAULTS_ALLOWLIST
        if unknown_defaults:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"unknown defaults keys (allowlist is {sorted(_DEFAULTS_ALLOWLIST)}): "
                f"{sorted(unknown_defaults)}",
                location="/defaults",
            )
        mct = defaults_raw.get("max_concurrent_tasks")
        if mct is not None and (not isinstance(mct, int) or isinstance(mct, bool) or mct < 1):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "defaults.max_concurrent_tasks must be an integer ≥ 1",
                location="/defaults/max_concurrent_tasks",
            )
        defaults_obj = DatasetDefaults(max_concurrent_tasks=mct)

    provenance_obj: dict[str, object] | None = None
    if "provenance" in raw:
        from ageval.config.provenance import validate_provenance

        provenance_obj = validate_provenance(raw.get("provenance"), location="/provenance")

    assets_obj = _parse_assets(raw.get("assets"))
    prepare_obj = _parse_prepare(raw.get("prepare"))

    # Reject unknown top-level keys beyond the wire schema.
    allowed = {
        "format",
        "dataset_id",
        "version",
        "tasks",
        "description",
        "defaults",
        "provenance",
        "assets",
        "prepare",
    }
    unknown_top = set(raw) - allowed
    if unknown_top:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"unknown dataset root keys: {sorted(unknown_top)}",
            location="/",
        )

    return DatasetManifest(
        format=fmt,
        dataset_id=dataset_id,
        version=version.strip(),
        tasks_root=tasks_root,
        description=description,
        defaults=defaults_obj,
        provenance=provenance_obj,
        assets=assets_obj,
        prepare=prepare_obj,
    )


def list_tasks(dataset_root: Path, *, manifest: DatasetManifest | None = None) -> list[str]:
    """Return sorted task ids under the dataset; fail closed on empty or mismatch."""
    root = dataset_root.expanduser().resolve(strict=False)
    man = manifest or load_dataset_manifest(root)
    tasks_dir = root / man.tasks_root
    if not tasks_dir.is_dir():
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"tasks root not found: {man.tasks_root}",
            location=man.tasks_root,
        )

    ids: list[str] = []
    for entry in sorted(tasks_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if not entry.is_dir():
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                f"non-directory entry under tasks root: {entry.name}",
                location=f"{man.tasks_root}/{entry.name}",
            )
        task_yaml = entry / TASK_CONFIG_FILENAME
        if not task_yaml.is_file():
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                f"missing {TASK_CONFIG_FILENAME} for task {entry.name!r}",
                location=f"{man.tasks_root}/{entry.name}/{TASK_CONFIG_FILENAME}",
            )
        try:
            text = task_yaml.read_text(encoding="utf-8")
            data = _parse_yaml_mapping(
                text,
                location=f"{man.tasks_root}/{entry.name}/{TASK_CONFIG_FILENAME}",
            )
        except ConfigError:
            raise
        except OSError as exc:
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                f"cannot read task config: {exc}",
                location=f"{man.tasks_root}/{entry.name}/{TASK_CONFIG_FILENAME}",
            ) from exc

        fmt = data.get("format")
        if fmt == DATASET_FORMAT:
            raise ConfigError(
                ERROR_INVALID_FORMAT,
                "task member must use ageval.task/1, not ageval.dataset/1",
                location=f"{man.tasks_root}/{entry.name}/{TASK_CONFIG_FILENAME}",
            )
        if fmt != "ageval.task/1":
            raise ConfigError(
                ERROR_INVALID_FORMAT,
                f"task member format must be ageval.task/1, got {fmt!r}",
                location=f"{man.tasks_root}/{entry.name}/{TASK_CONFIG_FILENAME}",
            )
        yaml_task_id = data.get("task_id")
        if not isinstance(yaml_task_id, str) or not yaml_task_id:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "task.yaml missing task_id",
                location=f"{man.tasks_root}/{entry.name}/task_id",
            )
        if yaml_task_id != entry.name:
            raise ConfigError(
                ERROR_UNKNOWN_TASK,
                f"task_id mismatch: directory={entry.name!r} yaml={yaml_task_id!r}",
                location=f"{man.tasks_root}/{entry.name}/task_id",
            )
        ids.append(entry.name)

    if not ids:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            "dataset has zero tasks (empty suite is not allowed)",
            location=man.tasks_root,
        )
    return ids


def resolve_task(
    dataset_root: Path,
    task_id: str,
    *,
    manifest: DatasetManifest | None = None,
) -> ResolvedTask:
    """Resolve *task_id* to a member directory under the dataset root."""
    if not isinstance(task_id, str) or not task_id.strip():
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            "task_id must be a non-empty string",
            location="--task",
        )
    task_id = task_id.strip()
    root = dataset_root.expanduser().resolve(strict=False)
    man = manifest or load_dataset_manifest(root)
    # Ensure suite is non-empty and members are consistent (also validates all ids).
    known = list_tasks(root, manifest=man)
    if task_id not in known:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"unknown task_id: {task_id!r} (not a member of this dataset)",
            location=f"{man.tasks_root}/{task_id}",
        )
    task_dir = (root / man.tasks_root / task_id).resolve(strict=False)
    task_config = task_dir / TASK_CONFIG_FILENAME
    return ResolvedTask(
        dataset_root=root,
        task_id=task_id,
        task_dir=task_dir,
        task_config_path=task_config,
        dataset_id=man.dataset_id,
        dataset_version=man.version,
    )


_SKIP_PROFILE_DIRS = frozenset({"tasks", "shared", "overlays", "evaluation", "environment"})


def _iter_profiles_documents(dataset_root: Path) -> list[Path]:
    """Dataset-root and one-level ``ageval.profiles/1`` candidates (not task trees)."""
    root = dataset_root.expanduser().resolve(strict=False)
    candidates: list[Path] = []
    if (root / "profiles.yaml").is_file():
        candidates.append(root / "profiles.yaml")
    candidates.extend(sorted(root.glob("profiles*.yaml")))
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in _SKIP_PROFILE_DIRS or child.name.startswith("."):
            continue
        candidates.extend(sorted(child.glob("*.yaml")))
    out: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _declared_overlay_member_paths(dataset_root: Path) -> list[str]:
    """Prefix closure of binding ``overlays:`` — not the whole ``overlays/`` tree."""
    from ageval.config.overlay_files import iter_overlay_files, overlay_paths_from_job_overlay
    from ageval.config.profiles import load_job_document

    root = dataset_root.expanduser().resolve(strict=False)
    declared: list[str] = []
    seen: set[str] = set()
    source_docs: list[str] = []
    for yaml_path in _iter_profiles_documents(root):
        try:
            job = load_job_document(yaml_path)
        except ConfigError:
            continue
        found = overlay_paths_from_job_overlay({"agent_profiles": job.profiles})
        if not found:
            continue
        rel_doc = _digest_member_file(root, yaml_path)
        if rel_doc is not None:
            source_docs.append(rel_doc)
        for path in found:
            if path in seen:
                continue
            seen.add(path)
            declared.append(path)
    if not declared:
        return []
    files = iter_overlay_files(root, declared, location="/overlays")
    rels: list[str] = []
    for file_path in files:
        rel = _digest_member_file(root, file_path)
        if rel is not None:
            rels.append(rel)
    return sorted(set(source_docs + rels))


def _digest_member_file(root: Path, file_path: Path) -> str | None:
    """Return package-relative posix path if *file_path* should enter packageDigest."""
    if not file_path.is_file():
        return None
    # Skip interpreter caches / most hidden files (design/02 digest notes).
    if "__pycache__" in file_path.parts or file_path.name.endswith(".pyc"):
        return None
    if file_path.name.startswith(".") and file_path.name not in {".gitignore"}:
        return None
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return None


def member_paths_for_digest(
    dataset_root: Path, *, manifest: DatasetManifest | None = None
) -> list[str]:
    """Stable ordered package-relative paths for suite digest input.

    Returns posix-relative paths under the dataset root: root ``ageval.yaml``,
    optional job-binding / env docs (``profiles.yaml``, ``env.example``,
    ``README.md``), optional Dataset-level ``shared/**``, files named by
    binding ``overlays:`` (not the whole ``overlays/`` tree), plus every file
    under each member directory, sorted. Does not compute hashes.
    Secrets (``.env``) are never included.
    """
    root = dataset_root.expanduser().resolve(strict=False)
    man = manifest or load_dataset_manifest(root)
    task_ids = list_tasks(root, manifest=man)
    paths: list[str] = ["ageval.yaml"]
    # #59 job overlay + credential docs at dataset root (no secrets).
    for name in ("profiles.yaml", "env.example", "README.md"):
        if (root / name).is_file():
            paths.append(name)
    # Any job document the dataset ships can change what a run does, so it is
    # digest input wherever it lives — not only at the root.
    for document in _iter_profiles_documents(root):
        rel = _digest_member_file(root, document)
        if rel is not None and rel not in paths:
            paths.append(rel)
    # #65 Dataset-level shared tree (if present) enters packageDigest / publish.
    shared_dir = root / "shared"
    if shared_dir.is_dir():
        for file_path in sorted(shared_dir.rglob("*")):
            rel = _digest_member_file(root, file_path)
            if rel is not None:
                paths.append(rel)
    for rel in _declared_overlay_member_paths(root):
        if rel not in paths:
            paths.append(rel)
    for tid in task_ids:
        task_dir = root / man.tasks_root / tid
        for file_path in sorted(task_dir.rglob("*")):
            rel = _digest_member_file(root, file_path)
            if rel is not None:
                paths.append(rel)
    return paths
