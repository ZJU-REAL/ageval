"""Decide whether an unsealed Attempt is resumed, rebuilt, or sealed as ERROR."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
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


def ensure_local_box(box: Path) -> Path:
    """Create the host-side attempt tree. Remote kinds do not bind-mount it."""
    for name in ("workspace", "home", "artifacts"):
        (box / name).mkdir(parents=True, exist_ok=True)
    return box


def attempt_state_dir(ctx: Any) -> Path:
    """Recovery files beside the box, not inside the tree the agent lists."""
    host = getattr(ctx, "host", None)
    rooted = getattr(host, "state_root", None)
    if isinstance(rooted, Path):
        rooted.mkdir(parents=True, exist_ok=True)
        return rooted
    path = Path(ctx.evidence.root) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def capture_box(ctx: Any, seq: int) -> int | None:
    """Snapshot the host bind root and advance the in-box cursor."""
    evidence = ctx.evidence
    box = ensure_local_box(evidence.path(AGENT_BOX_REL))
    store = ctx.checkpoints
    if store is None:
        store = CheckpointStore(evidence.root, box)
        ctx.checkpoints = store
    mirror = getattr(ctx.host, "mirror_checkpoint", None)
    if callable(mirror):
        mirror(box)
    store.capture(seq)
    state = attempt_state_dir(ctx)
    write_cursor(state, seq=seq, request_id=f"seq_{seq}")
    _sync_remote_state(ctx.host, state)
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
    ensure_local_box(ctx.evidence.path(AGENT_BOX_REL))
    if isinstance(nonce, str) and nonce:
        state = attempt_state_dir(ctx)
        write_nonce(state, nonce)
        _sync_remote_state(ctx.host, state)
    handle_fn = getattr(ctx.host, "runtime_handle", None)
    handle = handle_fn() if callable(handle_fn) else {}
    if not isinstance(handle, dict):
        handle = {}
    log.update_attempt_header(environment_handle=handle or None)


def _sync_remote_state(host: Any, state: Path) -> None:
    """Push nonce and cursor into a sandbox that does not mount ``state``."""
    if isinstance(getattr(host, "state_root", None), Path):
        return
    sync = getattr(host, "sync_box_state", None)
    if callable(sync):
        sync(state)


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
    """Wait out a busy probe.

    ``deadline_utc`` wins. Otherwise the in-flight row's ``at`` plus
    ``timeout_sec`` is the deadline. With neither, wait until the probe
    is no longer busy.
    """
    deadline = _busy_deadline(log)
    while True:
        if deadline is not None and datetime.now(UTC) >= deadline:
            return
        probe = await host.probe(handle)
        if probe.status != "busy":
            return
        delay = 0.05
        if deadline is not None:
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                return
            delay = min(delay, remaining)
        await asyncio.sleep(delay)


def _busy_deadline(log: ActivityLog) -> datetime | None:
    step = log.open_inflight(kinds=frozenset({"tool_call"}))
    if step is None:
        return None
    raw = step.payload.get("deadline_utc")
    if isinstance(raw, str) and raw:
        return _parse_utc(raw)
    timeout = step.payload.get("timeout_sec")
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        return None
    started = _parse_utc(step.at)
    if started is None:
        return None
    return started + timedelta(seconds=float(timeout))


async def _stop_old_handle(header: ActivityRecord, handle: dict[str, Any]) -> None:
    if header.payload.get("environment_kind") != "docker":
        return
    container_id = handle.get("container_id")
    if not isinstance(container_id, str) or not container_id.strip():
        return
    from ageval.plugins.contrib.docker.images import docker

    docker("rm", "-f", container_id.strip(), timeout=60.0)


def partial_output(ctx: Any) -> str | None:
    return read_partial_output(attempt_state_dir(ctx))


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
