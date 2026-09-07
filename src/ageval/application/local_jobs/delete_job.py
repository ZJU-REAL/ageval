"""Delete a local Viewer Job (single Attempt or cascading suite)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ageval.application.local_jobs import listing
from ageval.config.errors import ConfigError
from ageval.evidence.locators import (
    default_suite_runs_root,
    resolve_evidence_root,
    run_locator,
    safe_id_segment,
    suite_run_locator,
)
from ageval.registry.resolve import resolve_dataset_root

_FINISHED_PROGRESS = frozenset(
    {"complete", "completed", "finished", "done", "cancelled", "canceled"}
)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _confine(root: Path, path: Path, *, location: str) -> Path:
    root_r = root.expanduser().resolve(strict=False)
    cand = path.expanduser().resolve(strict=False)
    try:
        cand.relative_to(root_r)
    except ValueError as exc:
        raise ConfigError(
            "invalid_package",
            "path escapes dataset sandbox",
            location=location,
        ) from exc
    return cand


def _portable(root: Path, path: Path) -> str:
    rel = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    text = rel.as_posix()
    if not text or text.startswith(".."):
        raise ConfigError(
            "invalid_package",
            "path escapes dataset sandbox",
            location=text or ".",
        )
    return text


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() and not path.is_symlink():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            fp = Path(dirpath) / name
            if fp.is_symlink():
                continue
            try:
                total += int(fp.stat().st_size)
            except OSError:
                continue
    return total


def _collect_referenced_run_ids(summary: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        text = str(raw or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        ids.append(text)

    refs = summary.get("task_refs")
    if isinstance(refs, list):
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            _add(ref.get("run_id"))
            extra = ref.get("attempt_run_ids")
            if isinstance(extra, list):
                for item in extra:
                    _add(item)
            prev = ref.get("previous")
            if isinstance(prev, list):
                for item in prev:
                    if isinstance(item, dict):
                        _add(item.get("run_id"))
    tasks = summary.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict):
                _add(task.get("run_id"))
                prev = task.get("previous")
                if isinstance(prev, list):
                    for item in prev:
                        if isinstance(item, dict):
                            _add(item.get("run_id"))
    attempts = summary.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict):
                _add(attempt.get("run_id"))
                prev = attempt.get("previous")
                if isinstance(prev, list):
                    for item in prev:
                        if isinstance(item, dict):
                            _add(item.get("run_id"))
    return ids


def _suites_claiming_run(root: Path, run_id: str, *, exclude: str | None = None) -> list[str]:
    suite_root = default_suite_runs_root(root)
    if not suite_root.is_dir():
        return []
    claimants: list[str] = []
    for child in sorted(suite_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or (exclude and child.name == exclude):
            continue
        try:
            safe_id_segment(child.name, field="job_id")
        except ConfigError:
            continue
        summary = _load_json_object(child / "summary.json")
        if summary is None:
            continue
        if run_id in _collect_referenced_run_ids(summary):
            claimants.append(child.name)
    return claimants


def _suite_in_progress(suite_dir: Path) -> bool:
    if (suite_dir / "cancel.requested").is_file():
        return True
    progress = _load_json_object(suite_dir / "progress.json")
    if progress is None:
        return False
    status = str(progress.get("status") or "").strip().lower()
    return status not in _FINISHED_PROGRESS


def _resolve_attempt_dir(root: Path, run_id: str) -> Path | None:
    try:
        rid = safe_id_segment(run_id, field="run_id")
    except ConfigError:
        return None
    try:
        return resolve_evidence_root(root, rid, require_task_match=False)
    except ConfigError:
        return None


def _path_entry(
    root: Path,
    path: Path | None,
    *,
    locator: str,
    role: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    exists = bool(path is not None and path.exists())
    confined = _confine(root, path, location=locator) if path is not None else None
    if confined is not None:
        locator = _portable(root, confined)
    entry: dict[str, Any] = {
        "locator": locator,
        "bytes": _tree_bytes(confined) if confined is not None and exists else 0,
        "role": role,
        "exists": exists,
    }
    if run_id:
        entry["run_id"] = run_id
    return entry


def _confirm_token(job_id: str, kind: str, locators: list[str]) -> str:
    payload = "\n".join([job_id, kind, *locators])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class LocalJobsCommands:
    """List / get / preview / delete local Job trees. No Registry, no score rewrite."""

    def list_jobs(self, dataset_root: Path | str) -> dict[str, Any]:
        return listing.list_jobs(Path(dataset_root))

    def get_job(self, dataset_root: Path | str, job_id: str) -> dict[str, Any]:
        return listing.get_job(dataset_root, job_id)

    def get_job_task(self, dataset_root: Path | str, job_id: str, task_id: str) -> dict[str, Any]:
        return listing.get_job_task(dataset_root, job_id, task_id)

    def job_overlay_mapping(self, dataset_root: Path | str, job_id: str) -> dict[str, Any] | None:
        return listing.job_overlay_mapping(dataset_root, job_id)

    def preview_delete_job(self, dataset_root: Path | str, *, job_id: str) -> dict[str, Any]:
        root = resolve_dataset_root(dataset_root)
        job_id = safe_id_segment(job_id, field="job_id")
        suite_dir = _confine(
            root,
            default_suite_runs_root(root) / job_id,
            location=job_id,
        )
        if (suite_dir / "summary.json").is_file() or (suite_dir / "progress.json").is_file():
            return self._preview_suite(root, job_id=job_id, suite_dir=suite_dir)
        return self._preview_single(root, job_id=job_id)

    def delete_job(
        self,
        dataset_root: Path | str,
        *,
        job_id: str,
        confirm_token: str | None = None,
        yes: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_delete_job(dataset_root, job_id=job_id)
        if not preview.get("can_delete"):
            raw_err = preview.get("error")
            err = raw_err if isinstance(raw_err, dict) else {}
            raise ConfigError(
                str(err.get("code") or "invalid_request"),
                str(err.get("message") or "cannot delete job"),
                location=job_id,
            )
        token = (confirm_token or "").strip()
        if yes and not token:
            token = str(preview["confirm_token"])
        if not token:
            raise ConfigError(
                "confirm_required",
                "pass --yes or a confirm token from delete-preview",
                location=job_id,
            )
        if token != preview["confirm_token"]:
            raise ConfigError(
                "confirm_mismatch",
                "confirm token does not match current preview",
                location=job_id,
            )
        root = resolve_dataset_root(dataset_root)
        deleted: list[str] = []
        missing: list[str] = []
        for item in preview["paths"]:
            locator = str(item["locator"])
            path = _confine(root, root / locator, location=locator)
            if path.is_dir() or path.is_file():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted.append(locator)
            else:
                missing.append(locator)
        return {
            "ok": True,
            "job_id": preview["job_id"],
            "kind": preview["kind"],
            "deleted": deleted,
            "missing": missing,
            "bytes": preview["bytes"],
            "cascade_run_ids": preview["cascade_run_ids"],
        }

    def _preview_suite(self, root: Path, *, job_id: str, suite_dir: Path) -> dict[str, Any]:
        summary = _load_json_object(suite_dir / "summary.json") or {}
        run_ids = _collect_referenced_run_ids(summary)
        error: dict[str, str] | None = None
        warning: dict[str, str] | None = None
        if _suite_in_progress(suite_dir):
            warning = {
                "code": "job_in_progress",
                "message": "suite is still in progress or cancel is live",
            }
        stolen: list[str] = []
        for rid in run_ids:
            others = _suites_claiming_run(root, rid, exclude=job_id)
            if others:
                stolen.append(rid)
        if stolen:
            error = {
                "code": "job_claimed_elsewhere",
                "message": ("attempt still claimed by another suite: " + ", ".join(stolen)),
            }
        paths = [
            _path_entry(
                root,
                suite_dir,
                locator=suite_run_locator(job_id),
                role="suite",
            )
        ]
        for rid in run_ids:
            found = _resolve_attempt_dir(root, rid)
            paths.append(
                _path_entry(
                    root,
                    found,
                    locator=run_locator(rid),
                    role="attempt",
                    run_id=rid,
                )
            )
        locators = [str(p["locator"]) for p in paths]
        return {
            "ok": True,
            "job_id": job_id,
            "kind": "suite",
            "can_delete": error is None,
            "paths": paths,
            "bytes": sum(int(p["bytes"]) for p in paths),
            "cascade_run_ids": run_ids,
            "confirm_token": _confirm_token(job_id, "suite", locators),
            "error": error,
            "warning": warning,
        }

    def _preview_single(self, root: Path, *, job_id: str) -> dict[str, Any]:
        found = _resolve_attempt_dir(root, job_id)
        if found is None:
            raise ConfigError(
                "unknown_task",
                f"job not found: {job_id}",
                location=job_id,
            )
        claimants = _suites_claiming_run(root, job_id)
        error: dict[str, str] | None = None
        result = _load_json_object(found / "result.json") if found is not None else None
        if result is None:
            error = {
                "code": "job_in_progress",
                "message": "attempt has no sealed result.json (still running or incomplete)",
            }
        elif claimants:
            error = {
                "code": "job_inner_attempt",
                "message": "cannot delete an attempt that still belongs to a suite",
            }
        paths = [
            _path_entry(
                root,
                found,
                locator=run_locator(job_id),
                role="attempt",
                run_id=job_id,
            )
        ]
        locators = [str(p["locator"]) for p in paths]
        return {
            "ok": True,
            "job_id": job_id,
            "kind": "single",
            "can_delete": error is None,
            "paths": paths,
            "bytes": sum(int(p["bytes"]) for p in paths),
            "cascade_run_ids": [],
            "confirm_token": _confirm_token(job_id, "single", locators),
            "error": error,
        }
