"""Stage ``evaluation.collect`` before the evaluator.

An empty declaration returns without touching the box. Attempt-container
commands run before sidecar commands. The command string is not written
to evidence.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from ageval.attempt.artifact_harvest import _prune_excluded
from ageval.config.model import thaw
from ageval.environments.protocol import EnvironmentFailure
from ageval.evidence.redaction import redact_text
from ageval.evidence.store import VERIFIER_COLLECT_REL

_DEFAULT_TIMEOUT_SEC = 60.0
_MANIFEST = "manifest.json"


def declared_collect(ctx: Any) -> list[Any]:
    lock = getattr(ctx, "lock", None)
    if lock is None:
        return []
    refs = thaw(getattr(lock, "resolved_references", None) or {})
    raw = refs.get("evaluation_collect") if isinstance(refs, dict) else None
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


async def collect_declared_artifacts(ctx: Any) -> None:
    rows = declared_collect(ctx)
    if not rows:
        return
    if getattr(ctx, "regrade", False):
        _require_regrade_snapshot(ctx, rows)
        return
    ctx.assert_writers_stopped()
    indexed = list(enumerate(rows))
    main = [(index, row) for index, row in indexed if _is_main(row)]
    side = [(index, row) for index, row in indexed if not _is_main(row)]
    await _run_commands(ctx, main)
    copied = await _copy_paths(ctx, main)
    await _run_commands(ctx, side)
    copied.extend(await _copy_paths(ctx, side))
    _write_manifest(ctx, copied)
    ctx.record_fact("verifier_collected", {"entries": [_fact_entry(row) for row in rows]})


async def place_collected_artifacts(
    ctx: Any,
    host: Any,
    *,
    name: str | None = None,
) -> None:
    """Put staged paths back on one scoring host. No service: that host is one box."""
    entries = _read_manifest(ctx)
    if not entries:
        return
    root = ctx.evidence.path(VERIFIER_COLLECT_REL)
    for entry in entries:
        path = entry.get("path")
        index = entry.get("index")
        leaf = entry.get("name")
        if not isinstance(path, str) or not isinstance(index, int) or isinstance(index, bool):
            raise EnvironmentFailure(
                "environment_collect_missing",
                "verifier-collect manifest is missing a path",
            )
        if not isinstance(leaf, str) or not leaf:
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"verifier-collect manifest is missing a path for {path}",
            )
        staged = root / "entries" / str(index) / leaf
        if not staged.exists():
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"collect path missing: {path}",
            )
        await host.upload(staged, path)
    detail: Any = {"count": len(entries)}
    if name:
        detail["name"] = name
    ctx.record_fact("verifier_collect_placed", detail)


def _is_main(row: Any) -> bool:
    service = row.get("service")
    return not isinstance(service, str) or not service.strip() or service.strip() == "main"


def _exec_service(row: Any) -> str | None:
    if _is_main(row):
        return None
    service = row.get("service")
    assert isinstance(service, str)
    return service.strip()


def _service_label(row: Any) -> str:
    service = _exec_service(row)
    return "main" if service is None else service


def _path_of(row: Any) -> str | None:
    path = row.get("path")
    if isinstance(path, str) and path:
        return path
    return None


def _timeout(row: Any) -> float:
    raw = row.get("timeout_sec", _DEFAULT_TIMEOUT_SEC)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return _DEFAULT_TIMEOUT_SEC
    return float(raw)


def _fact_entry(row: Any) -> dict[str, str]:
    path = _path_of(row)
    entry = {
        "service": _service_label(row),
        "status": "copied" if path is not None else "ran",
    }
    if path is not None:
        entry["path"] = path
    return entry


async def _run_commands(ctx: Any, rows: list[tuple[int, Any]]) -> None:
    for _index, row in rows:
        command = row.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        service = _exec_service(row)
        result = await ctx.host.exec(
            ["sh", "-c", command],
            timeout_sec=_timeout(row),
            service=service,
        )
        if result.ok:
            continue
        path = _path_of(row)
        where = f" {path}" if path else ""
        label = "attempt" if service is None else service
        tail = redact_text(result.stderr or "")[-300:]
        raise EnvironmentFailure(
            "environment_collect_failed",
            f"collect command failed on {label}{where} exit {result.exit_code}: {tail}",
        )


async def _copy_paths(
    ctx: Any,
    rows: list[tuple[int, Any]],
) -> list[Any]:
    entries: list[Any] = []
    root = ctx.evidence.path(VERIFIER_COLLECT_REL)
    for index, row in rows:
        path = _path_of(row)
        if path is None:
            continue
        name = PurePosixPath(path).name or "root"
        dest = root / "entries" / str(index) / name
        await _download(ctx.host, path, dest, _exec_service(row))
        exclude = row.get("exclude")
        if isinstance(exclude, list) and dest.is_dir():
            _prune_excluded(dest, [str(part) for part in exclude])
        if not dest.exists():
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"collect path missing: {path}",
            )
        entries.append(
            {
                "index": index,
                "path": path,
                "service": _service_label(row),
                "name": name,
            }
        )
    return entries


async def _download(host: Any, source: str, dest: Path, service: str | None) -> None:
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if service is None:
            await host.download(source, dest)
        else:
            await host.download(source, dest, service=service)
    except EnvironmentFailure as exc:
        if exc.kind == "environment_collect_missing":
            raise
        if exc.kind == "environment_download_missing":
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"collect path missing: {source}",
            ) from exc
        raise
    if not dest.exists():
        raise EnvironmentFailure(
            "environment_collect_missing",
            f"collect path missing: {source}",
        )


def _write_manifest(ctx: Any, entries: list[Any]) -> None:
    if not entries:
        return
    path = ctx.evidence.path(VERIFIER_COLLECT_REL) / _MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": sorted(entries, key=lambda item: int(item["index"]))}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_manifest(ctx: Any) -> list[Any]:
    path = ctx.evidence.path(VERIFIER_COLLECT_REL) / _MANIFEST
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvironmentFailure(
            "environment_collect_missing",
            "verifier-collect manifest is not JSON",
        ) from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise EnvironmentFailure(
            "environment_collect_missing",
            "verifier-collect manifest is missing entries",
        )
    return entries


def _require_regrade_snapshot(ctx: Any, rows: list[Any]) -> None:
    wanted = [(index, row) for index, row in enumerate(rows) if _path_of(row)]
    if not wanted:
        return
    by_index = {
        int(entry["index"]): entry
        for entry in _read_manifest(ctx)
        if isinstance(entry.get("index"), int) and not isinstance(entry.get("index"), bool)
    }
    root = ctx.evidence.path(VERIFIER_COLLECT_REL)
    for index, row in wanted:
        path = _path_of(row)
        assert path is not None
        name = PurePosixPath(path).name or "root"
        staged = root / "entries" / str(index) / name
        entry = by_index.get(index)
        if (
            entry is None
            or entry.get("path") != path
            or entry.get("service") != _service_label(row)
            or entry.get("name") != name
            or not staged.exists()
        ):
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"collect path missing: {path}",
            )
