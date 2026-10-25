"""Decide whether an unsealed Attempt is resumed, rebuilt, or sealed as ERROR."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.environments.box_state import read_partial_output, write_cursor, write_nonce
from ageval.environments.protocol import ProbeStatus
from ageval.evidence.activity import ActivityLog, ActivityRecord
from ageval.evidence.attempt_record import RESULT_FILENAME
from ageval.evidence.checkpoints import CheckpointStore
from ageval.evidence.locators import default_runs_root
from ageval.evidence.store import ACTIVITY_LOG_REL, AGENT_BOX_REL

_NO_SEAL = frozenset(
    {
        "attempt_already_settled",
        "attempt_still_busy",
        "locked_config_mismatch",
        "activity_log_missing",
    }
)


def leaves_result_unwritten(title: str | None) -> bool:
    """True when recovery must exit 2 without sealing ``result.json``."""
    return title in _NO_SEAL


def new_nonce() -> str:
    return f"nce_{uuid.uuid4().hex[:12]}"


def write_attempt_header(
    log: ActivityLog,
    *,
    run_id: str,
    trial_id: str,
    attempt_id: str,
    task_id: str,
    attempt_index: int,
    suite_run_id: str | None,
    digest: str,
    environment_kind: str,
    nonce: str,
) -> ActivityRecord:
    return log.append(
        request_id=f"att_{attempt_id}",
        kind="attempt",
        status="completed",
        payload={
            "run_id": run_id,
            "trial_id": trial_id,
            "attempt_id": attempt_id,
            "task_id": task_id,
            "attempt_index": attempt_index,
            "suite_run_id": suite_run_id,
            "locked_config_digest": digest,
            "environment_kind": environment_kind,
            "environment_nonce": nonce,
            "environment_handle": None,
        },
    )


def find_unsealed_attempt(
    dataset_root: Path,
    *,
    suite_run_id: str,
    task_id: str,
    attempt_index: int,
    digest: str,
) -> Path | None:
    """Unsealed run dir whose header matches this suite slot and lock digest."""
    runs = default_runs_root(dataset_root)
    if not runs.is_dir():
        return None
    found: list[Path] = []
    for path in runs.iterdir():
        if not path.is_dir() or (path / RESULT_FILENAME).is_file():
            continue
        header = _header(path)
        if header is None:
            continue
        payload = header.payload
        if payload.get("suite_run_id") != suite_run_id:
            continue
        if payload.get("task_id") != task_id:
            continue
        if payload.get("attempt_index") != attempt_index:
            continue
        if payload.get("locked_config_digest") != digest:
            continue
        found.append(path)
    if not found:
        return None
    found.sort(key=lambda item: item.stat().st_mtime)
    return found[-1]


def load_activity(attempt_dir: Path) -> ActivityLog:
    return ActivityLog.open(attempt_dir / ACTIVITY_LOG_REL)


def capture_box(ctx: Any, seq: int) -> int | None:
    """Snapshot the host bind root and advance the in-box cursor."""
    evidence = ctx.evidence
    box = evidence.path(AGENT_BOX_REL)
    if not box.is_dir():
        return None
    store = ctx.checkpoints
    if store is None:
        store = CheckpointStore(evidence.root, box)
        ctx.checkpoints = store
    mirror = getattr(ctx.host, "mirror_checkpoint", None)
    if callable(mirror):
        mirror(box)
    store.capture(seq)
    write_cursor(box, seq=seq, request_id=f"seq_{seq}")
    return seq


def publish_environment_handle(ctx: Any) -> None:
    """Write the nonce file and store the live handle on the attempt header."""
    log: ActivityLog | None = ctx.activity
    if log is None:
        return
    header = log.header()
    if header is None:
        return
    nonce = header.payload.get("environment_nonce")
    box = ctx.evidence.path(AGENT_BOX_REL)
    if isinstance(nonce, str) and nonce and box.is_dir():
        write_nonce(box, nonce)
    handle_fn = getattr(ctx.host, "runtime_handle", None)
    handle = handle_fn() if callable(handle_fn) else {}
    if not isinstance(handle, dict):
        handle = {}
    log.update_attempt_header(environment_handle=handle or None)


def restore_checkpoint(ctx: Any, seq: int) -> None:
    box = ctx.evidence.path(AGENT_BOX_REL)
    store = CheckpointStore(ctx.evidence.root, box)
    store.restore(seq)
    ctx.checkpoints = store


async def classify_environment(ctx: Any) -> str:
    """Attach a live box or mark a rebuild. Returns attached, rebuild, or busy."""
    log: ActivityLog = ctx.activity
    header = log.header()
    if header is None:
        ctx.recovery_rebuild = True
        return "rebuild"
    handle = header.payload.get("environment_handle")
    if not isinstance(handle, dict):
        handle = {}
    probe = await ctx.host.probe(handle)
    if probe.status == "busy":
        await _wait_until_idle(ctx.host, handle, log)
        probe = await ctx.host.probe(handle)
        if probe.status == "busy":
            return "busy"
    nonce_ok = probe.status == "idle" and probe.nonce == header.payload.get("environment_nonce")
    last = probe.last_exit if isinstance(probe.last_exit, dict) else None
    last_request = last.get("request_id") if last is not None else None
    adopt = nonce_ok and isinstance(last_request, str) and log.matches_inflight_tool(last_request)
    cursor_ok = nonce_ok and probe.cursor_seq == log.last_completed_env_seq()
    if adopt or cursor_ok:
        await ctx.host.attach(handle)
        ctx.recovery_attached = True
        _set_reattached(ctx.host, True)
        if adopt:
            _adopt_last_exit(ctx, probe)
        return "attached"
    await _stop_old_handle(header, handle)
    ctx.recovery_rebuild = True
    _set_reattached(ctx.host, False)
    return "rebuild"


def _adopt_last_exit(ctx: Any, probe: ProbeStatus) -> None:
    last = probe.last_exit
    log: ActivityLog = ctx.activity
    if not isinstance(last, dict):
        return
    request_id = last.get("request_id")
    if not isinstance(request_id, str) or not log.matches_inflight_tool(request_id):
        return
    inflight = None
    for record in log.records:
        if record.kind == "tool_call" and record.request_id == request_id:
            inflight = record
    if inflight is None:
        return
    from ageval.evidence.activity import ActivityScope

    scope = ActivityScope(
        log,
        session_id=str(inflight.payload.get("session_id") or ""),
        invoke_request_id=str(inflight.payload.get("invoke_request_id") or ""),
        environment_reattached=True,
    )
    exit_code = last.get("exit_code")
    code = exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    content = last.get("stdout") if isinstance(last.get("stdout"), str) else ""
    stderr = last.get("stderr") if isinstance(last.get("stderr"), str) else ""

    def prepare(seq: int) -> dict[str, int | None]:
        return {"checkpoint_seq": capture_box(ctx, seq)}

    scope.record_tool_call_completed(
        str(inflight.payload.get("tool_call_id") or ""),
        outcome="ok" if code == 0 else "error",
        exit_code=code,
        content=content,
        stderr=stderr,
        request_id=request_id,
        prepare=prepare,
    )


async def _wait_until_idle(host: Any, handle: dict[str, Any], log: ActivityLog) -> None:
    raw = log.inflight_tool_deadline()
    deadline = _parse_utc(raw) if raw else None
    if deadline is None:
        return
    while datetime.now(UTC) < deadline:
        await asyncio.sleep(0.25)
        probe = await host.probe(handle)
        if probe.status != "busy":
            return


async def _stop_old_handle(header: ActivityRecord, handle: dict[str, Any]) -> None:
    if header.payload.get("environment_kind") != "docker":
        return
    container_id = handle.get("container_id")
    if not isinstance(container_id, str) or not container_id.strip():
        return
    from ageval.plugins.contrib.docker.images import docker

    docker("rm", "-f", container_id.strip(), timeout=60.0)


def partial_output(ctx: Any) -> str | None:
    box = ctx.evidence.path(AGENT_BOX_REL)
    if not box.is_dir():
        return None
    return read_partial_output(box)


def _set_reattached(host: Any, value: bool) -> None:
    if hasattr(host, "reattached"):
        host.reattached = value


def _header(attempt_dir: Path) -> ActivityRecord | None:
    path = attempt_dir / ACTIVITY_LOG_REL
    if not path.is_file():
        return None
    try:
        log = ActivityLog.open(path)
    except ConfigError:
        return None
    return log.header()


def _parse_utc(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
