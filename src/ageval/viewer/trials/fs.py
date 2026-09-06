"""Trial file tree and file preview for viewer."""

from __future__ import annotations

import contextlib
import mimetypes
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.evidence.locators import safe_id_segment
from ageval.viewer.jobs import get_job
from ageval.viewer.trials.constants import MAX_FILE_BYTES, MAX_TREE_ENTRIES, TEXT_SUFFIXES
from ageval.viewer.trials.paths import (
    _read_json_object,
    _safe_run_id,
    _safe_under,
    resolve_evidence_root,
)


def _scope_base(evidence: Path, scope: str) -> Path:
    scope = (scope or "root").strip().lower()
    mapping = {
        "root": evidence,
        "agent": evidence / "agent",
        "eval": evidence / "evaluation",
        "evaluation": evidence / "evaluation",
        "verifier": evidence / "evaluation",
        "artifacts": evidence / "harness",
        "harness": evidence / "harness",
        "lock": evidence,  # single file handled by caller
    }
    if scope not in mapping:
        raise ConfigError(
            "invalid_package",
            f"unknown tree scope: {scope!r}",
            location="scope",
        )
    return mapping[scope]


def trial_tree(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
    *,
    scope: str = "root",
) -> dict[str, Any]:
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    # Ensure job exists (sandbox + membership)
    get_job(root, job_id)
    evidence = resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    scope_norm = (scope or "root").strip().lower()

    # Special multi-root scopes for verifier
    if scope_norm in {"verifier", "eval", "evaluation"}:
        from ageval.evidence.attempt_record import RESULT_FILENAME, result_path

        entries: list[dict[str, Any]] = []
        for sub in (
            evidence / "evaluation",
            evidence / "eval_staging",
            result_path(evidence),
        ):
            if sub.is_file():
                st = sub.stat()
                rel = (
                    RESULT_FILENAME
                    if sub.name == RESULT_FILENAME
                    else (sub.name if sub.parent == evidence else str(sub.relative_to(evidence)))
                )
                entries.append(
                    {
                        "path": rel,
                        "name": sub.name,
                        "type": "file",
                        "size": st.st_size,
                    }
                )
            elif sub.is_dir():
                remain = MAX_TREE_ENTRIES - len(entries)
                entries.extend(_walk_tree(evidence, sub, max_entries=remain))
        return {
            "ok": True,
            "run_id": rid,
            "scope": "verifier",
            "entries": entries[:MAX_TREE_ENTRIES],
            "truncated": len(entries) > MAX_TREE_ENTRIES,
        }

    if scope_norm == "artifacts":
        # Publishable / harness-produced product files — not root runtime bookkeeping.
        # Prefer package artifacts/ then harness/ subtree (e.g. terminal.json, published JSON).
        entries = []
        for sub in (
            evidence / "artifacts",
            evidence / "harness",
            evidence / "agent" / "artifacts",
        ):
            if sub.is_dir():
                entries.extend(
                    _walk_tree(evidence, sub, max_entries=MAX_TREE_ENTRIES - len(entries))
                )
            elif sub.is_file():
                with contextlib.suppress(OSError, ValueError):
                    entries.append(
                        {
                            "path": str(sub.relative_to(evidence)),
                            "name": sub.name,
                            "type": "file",
                            "size": sub.stat().st_size,
                        }
                    )
        return {
            "ok": True,
            "run_id": rid,
            "scope": "artifacts",
            "entries": entries[:MAX_TREE_ENTRIES],
            "truncated": len(entries) > MAX_TREE_ENTRIES,
            "note": "publishable outputs under artifacts/ and harness/; "
            "runtime bookkeeping is under Runtime tab",
        }

    if scope_norm == "lock":
        lock_path = evidence / "lock.json"
        entries = []
        if lock_path.is_file():
            entries.append(
                {
                    "path": "lock.json",
                    "name": "lock.json",
                    "type": "file",
                    "size": lock_path.stat().st_size,
                }
            )
        return {"ok": True, "run_id": rid, "scope": "lock", "entries": entries, "truncated": False}

    if scope_norm in {"runtime", "log"}:  # "log" accepted as alias
        entries = []
        for name in ("effects.jsonl", "cleanup.json", "summary.json", "agent.json", "harness.json"):
            p = evidence / name
            if p.is_file():
                entries.append(
                    {
                        "path": name,
                        "name": name,
                        "type": "file",
                        "size": p.stat().st_size,
                    }
                )
        return {
            "ok": True,
            "run_id": rid,
            "scope": "runtime",
            "entries": entries,
            "truncated": False,
        }

    base = _scope_base(evidence, scope_norm)
    if not base.exists():
        return {
            "ok": True,
            "run_id": rid,
            "scope": scope_norm,
            "entries": [],
            "truncated": False,
            "note": f"no files under scope {scope_norm!r}",
        }
    if base.is_file():
        entries = [
            {
                "path": str(base.relative_to(evidence)),
                "name": base.name,
                "type": "file",
                "size": base.stat().st_size,
            }
        ]
    else:
        entries = _walk_tree(evidence, base, max_entries=MAX_TREE_ENTRIES)

    # Agent scope: attach profile_id / group labels for virtual SPA folders (#27).
    groups: list[dict[str, Any]] | None = None
    if scope_norm == "agent":
        entries, groups = _annotate_agent_tree_profiles(evidence, entries)

    return {
        "ok": True,
        "run_id": rid,
        "scope": scope_norm,
        "entries": entries,
        "groups": groups,
        "truncated": len(entries) >= MAX_TREE_ENTRIES,
    }


def _annotate_agent_tree_profiles(
    evidence: Path,
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Stamp profile_id on agent/invocations/* entries; build group list.

    Disk layout stays flat; groups are read-side only. Real relative paths
    are preserved for file preview.
    """
    inv_root = evidence / "agent" / "invocations"
    if not inv_root.is_dir():
        return entries, None

    inv_meta: dict[str, dict[str, Any]] = {}
    try:
        inv_dirs = sorted(p for p in inv_root.iterdir() if p.is_dir())
    except OSError:
        inv_dirs = []
    for inv in inv_dirs:
        meta = _read_json_object(inv / "metadata.json") or {}
        pid = meta.get("profile_id")
        inv_meta[inv.name] = {
            "profile_id": pid if isinstance(pid, str) else None,
            "model": meta.get("model") or meta.get("locked_model"),
            "dirname": inv.name,
        }

    if not inv_meta:
        return entries, None

    annotated: list[dict[str, Any]] = []
    for e in entries:
        path = str(e.get("path") or "")
        # agent/invocations/<dirname>/...
        parts = path.split("/")
        profile_id = None
        inv_dirname = None
        if len(parts) >= 3 and parts[0] == "agent" and parts[1] == "invocations":
            inv_dirname = parts[2]
            meta = inv_meta.get(inv_dirname) or {}
            profile_id = meta.get("profile_id")
        ne = dict(e)
        if profile_id:
            ne["profile_id"] = profile_id
        if inv_dirname:
            ne["invocation"] = inv_dirname
        annotated.append(ne)

    # Stable group order: first appearance in inv dir sort order.
    seen: list[str] = []
    groups: list[dict[str, Any]] = []
    for inv_name in sorted(inv_meta.keys()):
        meta = inv_meta[inv_name]
        pid = meta.get("profile_id")
        key = pid if isinstance(pid, str) and pid else inv_name
        if key in seen:
            continue
        seen.append(key)
        groups.append(
            {
                "key": key,
                "profile_id": pid if isinstance(pid, str) else None,
                "label": pid if isinstance(pid, str) else inv_name,
            }
        )
    return annotated, groups if groups else None


def _walk_tree(evidence: Path, base: Path, *, max_entries: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if max_entries <= 0:
        return out
    try:
        paths = sorted(base.rglob("*"), key=lambda p: str(p).lower())
    except OSError:
        return out
    for p in paths:
        if len(out) >= max_entries:
            break
        try:
            rel = str(p.relative_to(evidence))
            if p.is_dir():
                out.append({"path": rel, "name": p.name, "type": "dir", "size": None})
            elif p.is_file():
                out.append(
                    {
                        "path": rel,
                        "name": p.name,
                        "type": "file",
                        "size": p.stat().st_size,
                    }
                )
        except (OSError, ValueError):
            continue
    return out


def trial_file(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
    *,
    relpath: str,
) -> dict[str, Any]:
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    get_job(root, job_id)
    evidence = resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    path = _safe_under(evidence, relpath)
    if not path.is_file():
        raise ConfigError(
            "unknown_task",
            f"file not found: {relpath}",
            location=relpath,
        )
    size = path.stat().st_size
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    suffix = path.suffix.lower()
    # Never preview env/secret-like basenames even if under evidence
    if path.name in {".env", ".env.local", ".env.production"} or path.name.startswith(".env."):
        return {
            "ok": True,
            "run_id": rid,
            "path": relpath,
            "name": path.name,
            "size": size,
            "media_type": mime,
            "encoding": "redacted",
            "truncated": False,
            "content": None,
            "note": "secret-like filename; content not shown",
        }
    is_text = (
        suffix in TEXT_SUFFIXES
        or mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/x-yaml"}
    )
    if not is_text:
        return {
            "ok": True,
            "run_id": rid,
            "path": relpath,
            "name": path.name,
            "size": size,
            "media_type": mime,
            "encoding": "binary",
            "truncated": False,
            "content": None,
            "note": "binary file; preview not shown",
        }
    if size > MAX_FILE_BYTES:
        raw = path.read_bytes()[:MAX_FILE_BYTES]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "run_id": rid,
            "path": relpath,
            "name": path.name,
            "size": size,
            "media_type": mime,
            "encoding": "utf-8",
            "truncated": True,
            "content": text,
            "note": f"truncated to first {MAX_FILE_BYTES} bytes",
        }
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "run_id": rid,
        "path": relpath,
        "name": path.name,
        "size": size,
        "media_type": mime,
        "encoding": "utf-8",
        "truncated": False,
        "content": text,
    }
