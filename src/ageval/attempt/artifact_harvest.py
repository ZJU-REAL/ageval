"""Collect declared artifacts from the box after writers stop.

``run.py`` is a parent process. Agent writes live in the box. Shared-FS kinds
already have those bytes on the parent dest when the task published; remote
kinds do not. This step fills *missing* publishable files via Protocol
``download`` from ``/attempt/workspace/<basename>``, and copies ``kind: tree``
snapshots once with ``exclude``. It does not scrape chat and does not run on
every invoke.
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import Any

from ageval.config.model import thaw
from ageval.environments.protocol import ARTIFACTS_PATH, WORKSPACE_PATH, EnvironmentFailure
from ageval.evidence.store import TASK_ARTIFACTS_REL


async def harvest_workspace_artifacts(ctx: Any) -> None:
    """Copy missing publishable artifacts from the box workspace onto evidence."""
    ctx.assert_writers_stopped()
    caps = getattr(ctx.host, "capabilities", None)
    if caps is not None and not getattr(caps, "download", False):
        return
    refs = thaw(getattr(ctx.lock, "resolved_references", None) or {})
    declared = refs.get("artifacts") if isinstance(refs, dict) else None
    if not isinstance(declared, list) or not declared:
        return
    staged = ctx.evidence.path(TASK_ARTIFACTS_REL)
    staged.mkdir(parents=True, exist_ok=True)
    pulled: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for item in declared:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id") or "").strip()
        rel = str(item.get("path") or "").strip()
        if not aid or not rel:
            continue
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            missing.append(aid)
            continue
        kind = str(item.get("kind") or "file").strip() or "file"
        if kind == "tree":
            dest = staged / aid
            exclude = [str(part) for part in (item.get("exclude") or [])]
            status = await _harvest_tree(ctx, dest=dest, rel=rel, exclude=exclude)
        else:
            dest = staged / f"{aid}{Path(rel_path.name).suffix or '.json'}"
            status = await _harvest_file(ctx, dest=dest, rel_path=rel_path)
        if status == "pulled":
            pulled.append(aid)
        elif status == "skipped":
            skipped.append(aid)
        else:
            missing.append(aid)
    ctx.record_fact(
        "artifacts_harvested",
        {"pulled": pulled, "skipped": skipped, "missing": missing},
    )


async def _harvest_file(ctx: Any, *, dest: Path, rel_path: Path) -> str:
    if dest.is_file():
        return "skipped"
    name = rel_path.name
    posix = rel_path.as_posix().lstrip("/")
    # Declared path is evidence-shaped (artifacts/foo.json). Agents write
    # the basename in the box workspace. Prefer that, then the posix path.
    candidates = [f"{WORKSPACE_PATH}/{name}"]
    if posix != name:
        candidates.append(f"{WORKSPACE_PATH}/{posix}")
        candidates.append(f"{ARTIFACTS_PATH}/{name}")
    for source in candidates:
        try:
            await ctx.host.download(source, dest)
        except EnvironmentFailure:
            continue
        return "pulled"
    return "missing"


async def _harvest_tree(ctx: Any, *, dest: Path, rel: str, exclude: list[str]) -> str:
    if dest.is_dir() and any(dest.iterdir()):
        return "skipped"
    source = _tree_box_path(rel)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    try:
        await ctx.host.download(source, dest)
    except EnvironmentFailure:
        return "missing"
    if not dest.exists():
        return "missing"
    _prune_excluded(dest, exclude)
    return "pulled"


def _tree_box_path(rel: str) -> str:
    posix = Path(rel).as_posix().strip().strip("/")
    if posix in {"", ".", "workspace"}:
        return WORKSPACE_PATH
    if posix.startswith("workspace/"):
        return f"{WORKSPACE_PATH}/{posix[len('workspace/') :]}"
    return f"{WORKSPACE_PATH}/{posix}"


def _prune_excluded(root: Path, exclude: list[str]) -> None:
    if not exclude or not root.exists():
        return
    if root.is_file():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        rel = path.relative_to(root)
        if not _excluded(rel, exclude):
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def regrade_harvest_gap(lock: Any, staged: Path) -> tuple[str, tuple[str, ...]] | None:
    """Why this snapshot cannot be regraded, or None when every declared artifact is there.

    ``undeclared`` means the locked task has no ``artifacts.publishable`` rows.
    ``missing`` lists ids whose file or tree snapshot is absent or empty.
    Trajectory text is not an input.
    """
    refs = thaw(getattr(lock, "resolved_references", None) or {})
    declared = refs.get("artifacts") if isinstance(refs, dict) else None
    rows = (
        [item for item in declared if isinstance(item, dict)] if isinstance(declared, list) else []
    )
    if not rows:
        return ("undeclared", ())
    missing: list[str] = []
    for item in rows:
        aid = str(item.get("id") or "").strip() or "?"
        dest = _snapshot_path(staged, item)
        if dest is None or not _snapshot_present(dest, item):
            missing.append(aid)
    if missing:
        return ("missing", tuple(missing))
    return None


def _snapshot_path(staged: Path, item: dict[str, Any]) -> Path | None:
    aid = str(item.get("id") or "").strip()
    rel = str(item.get("path") or "").strip()
    if not aid or not rel:
        return None
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return None
    if _publishable_kind(item) == "tree":
        return staged / aid
    suffix = rel_path.suffix or ".json"
    return staged / f"{aid}{suffix}"


def _publishable_kind(item: dict[str, Any]) -> str:
    return str(item.get("kind") or "file").strip() or "file"


def _snapshot_present(dest: Path, item: dict[str, Any]) -> bool:
    if _publishable_kind(item) == "tree":
        return dest.is_dir() and any(dest.iterdir())
    return dest.is_file() and dest.stat().st_size > 0


def _excluded(rel: Path, patterns: list[str]) -> bool:
    posix = rel.as_posix()
    for pattern in patterns:
        text = str(pattern).strip()
        if not text:
            continue
        if any(fnmatch.fnmatch(part, text) for part in rel.parts):
            return True
        if fnmatch.fnmatch(posix, text) or fnmatch.fnmatch(rel.name, text):
            return True
    return False
