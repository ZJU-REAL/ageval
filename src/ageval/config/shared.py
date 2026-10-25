"""Dataset-level ``shared/`` layout helpers (#65 layout, #68 import namespaces).

Design authority: ``docs/design/02-schemas-and-config.md`` (Dataset 级 shared/).
"""

from __future__ import annotations

from pathlib import Path

from ageval.config.errors import ERROR_INVALID_PACKAGE, ConfigError

# Top-level names under shared/ that must not exist (ban gold/secrets confusion).
_FORBIDDEN_SHARED_TOP_LEVEL = frozenset(
    {
        "evaluation",  # gold lives only under tasks/*/evaluation/
        ".env",
    }
)

# Reserved Dataset package name — task members must not own this top-level name.
_RESERVED_TOP_LEVEL_PACKAGE = "shared"


def infer_dataset_root_from_task(task_dir: Path) -> Path | None:
    """Best-effort dataset root from a member task directory.

    Walks ancestors until a ``ageval.yaml`` is found (supports nested
    ``tasks.root``, e.g. ``members/group/<task_id>``).
    """
    cur = task_dir.expanduser().resolve(strict=False)
    # Do not treat the task dir itself as the dataset root.
    for parent in cur.parents:
        if (parent / "ageval.yaml").is_file():
            return parent
    return None


def top_level_import_names(lib_dir: Path) -> set[str]:
    """Top-level Python import names under a ``lib/`` directory.

    Collects bare module stems (``foo.py`` → ``foo``) and package directories
    that contain ``__init__.py`` or any nested content used as a namespace.
    Skips ``__pycache__`` and private ``_*`` only when they are not importable
    packages authors would deliberately share — ``_*`` names are still checked
    if present as modules (collision risk is real).
    """
    if not lib_dir.is_dir():
        return set()
    names: set[str] = set()
    for child in lib_dir.iterdir():
        if child.name == "__pycache__" or child.name.endswith(".pyc"):
            continue
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix == ".py":
            if child.name == "__init__.py":
                continue
            names.add(child.stem)
        elif child.is_dir():
            # Treat any non-cache directory as an importable package name.
            names.add(child.name)
    return names


def _task_ids_under(
    root: Path,
    tasks_root: str,
    task_ids: list[str] | None,
) -> list[str]:
    if task_ids is not None:
        return list(task_ids)
    tasks_dir = root / tasks_root
    if not tasks_dir.is_dir():
        return []
    return sorted(p.name for p in tasks_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def find_task_shared_shadows(
    dataset_root: Path,
    *,
    tasks_root: str = "tasks",
    task_ids: list[str] | None = None,
) -> list[str]:
    """Return relative paths of task-owned top-level ``shared`` that would shadow Dataset.

    Forbidden when present:

    - ``tasks/<id>/shared/`` (directory)
    - ``tasks/<id>/shared.py`` (module)
    """
    root = dataset_root.expanduser().resolve(strict=False)
    hits: list[str] = []
    for tid in _task_ids_under(root, tasks_root, task_ids):
        task_dir = root / tasks_root / tid
        shared_dir_path = task_dir / _RESERVED_TOP_LEVEL_PACKAGE
        shared_mod = task_dir / f"{_RESERVED_TOP_LEVEL_PACKAGE}.py"
        if shared_dir_path.exists():
            hits.append(f"{tasks_root}/{tid}/{_RESERVED_TOP_LEVEL_PACKAGE}")
        if shared_mod.is_file():
            hits.append(f"{tasks_root}/{tid}/{_RESERVED_TOP_LEVEL_PACKAGE}.py")
    return hits


def validate_shared_layout(
    dataset_root: Path,
    *,
    tasks_root: str = "tasks",
    task_ids: list[str] | None = None,
) -> None:
    """Fail closed on forbidden ``shared/`` content or task ``shared`` shadows (#68).

    No-op when ``shared/`` is absent **and** no task owns top-level ``shared``.
    Task-level ``shared`` shadow is always checked when a dataset root is known.
    """
    root = dataset_root.expanduser().resolve(strict=False)
    shared = root / "shared"
    if shared.exists():
        if not shared.is_dir():
            raise ConfigError(
                ERROR_INVALID_PACKAGE,
                "shared must be a directory when present",
                location="shared",
            )

        for name in sorted(_FORBIDDEN_SHARED_TOP_LEVEL):
            bad = shared / name
            if bad.exists():
                raise ConfigError(
                    ERROR_INVALID_PACKAGE,
                    f"forbidden path under shared/: {name} "
                    "(gold/secrets must not live under Dataset shared/)",
                    location=f"shared/{name}",
                )

        # Also reject nested .env anywhere under shared/
        for env_file in shared.rglob(".env"):
            if env_file.is_file():
                try:
                    rel = env_file.relative_to(root).as_posix()
                except ValueError:
                    rel = "shared/.env"
                raise ConfigError(
                    ERROR_INVALID_PACKAGE,
                    "host secrets must not live under shared/ (.env forbidden)",
                    location=rel,
                )

    shadows = find_task_shared_shadows(root, tasks_root=tasks_root, task_ids=task_ids)
    if shadows:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            "task must not own top-level name 'shared' "
            "(shadows Dataset package shared when both parents are on sys.path): "
            + "; ".join(shadows),
            location=shadows[0],
        )
