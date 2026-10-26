"""Cold rebuild restores the checkpoint before after_environment."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.run import _error_fact
from ageval.attempt import run_attempt
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import cleanup, environment, evaluate, record
from ageval.attempt.recover import write_attempt_header
from ageval.environments.protocol import ExecResult
from ageval.evaluation.bind import bind_result
from ageval.evaluation.error_record import RecordedError
from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.evidence.attempt_record import write_attempt_result
from ageval.evidence.checkpoints import CheckpointStore
from ageval.evidence.store import AGENT_BOX_REL, AttemptEvidenceStore
from ageval.evidence.system_effect import command_system_effect
from ageval.plugins.protocol import ExtensionGraph, HandlerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import (
    AFTER_ENVIRONMENT,
    AFTER_ENVIRONMENT_READY,
    BEFORE_ENVIRONMENT,
    ENVIRONMENT_SETUP,
)
from ageval.runtime.cancellation import CancellationSignal


class _Host:
    kind = "local"

    def __init__(self, box: Path, *, exit_code: int = 0) -> None:
        self.box = box
        self.exit_code = exit_code
        self.execs: list[tuple[list[str], str]] = []

    async def start(self, *, force_build: bool = False) -> None:
        del force_build

    async def upload(self, source: Path, dest: str) -> None:
        del dest
        target = self.box / "workspace"
        target.mkdir(parents=True, exist_ok=True)
        for path in Path(source).rglob("*"):
            if not path.is_file():
                continue
            dest_path = target / path.relative_to(source)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(path.read_bytes())

    async def exec(self, argv: list[str], timeout_sec: float | None = None) -> ExecResult:
        del timeout_sec
        note = self.box / "workspace" / "note.txt"
        text = note.read_text(encoding="utf-8") if note.is_file() else ""
        self.execs.append((list(argv), text))
        return ExecResult(exit_code=self.exit_code, stdout="", stderr="")


def _graph(order: list[str]) -> ExtensionGraph:
    graph = ExtensionGraph(profile_id="solver")

    def _handler(name: str):
        async def handler(ctx: AttemptCtx, value: object, nxt):  # type: ignore[no-untyped-def]
            if name == AFTER_ENVIRONMENT:
                note = ctx.evidence.path(AGENT_BOX_REL) / "workspace" / "note.txt"
                order.append(note.read_text(encoding="utf-8") if note.is_file() else "")
            else:
                order.append(name)
            return await nxt(value)

        return handler

    for slot in (
        BEFORE_ENVIRONMENT,
        AFTER_ENVIRONMENT_READY,
        ENVIRONMENT_SETUP,
        AFTER_ENVIRONMENT,
    ):
        graph.chains[slot] = [
            HandlerRef(
                plugin_id="probe",
                handler=_handler(slot),
                priority=0,
                source="test",
                slot=slot,
            )
        ]
    return graph


def _ctx(tmp_path: Path, host: _Host, log: ActivityLog, graph: ExtensionGraph) -> AttemptCtx:
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=SimpleNamespace(force_build=False),  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=host,  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


def _log(tmp_path: Path, *, system: bool, checkpoint: int | None) -> ActivityLog:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    write_attempt_header(
        log,
        run_id="r",
        trial_id="t",
        attempt_id="a",
        task_id="task",
        attempt_index=0,
        suite_run_id=None,
        digest="sha256:abc",
        environment_kind="local",
        nonce="nce_test",
    )
    if system:
        scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
        scope.record_tool_call_in_flight(
            "call_pkg",
            "execute",
            "execute",
            {"command": "apt-get install -y tmux"},
            system_effect=True,
        )
        scope.record_tool_call_completed(
            "call_pkg",
            outcome="ok",
            exit_code=0,
            content="",
            checkpoint_seq=checkpoint,
        )
    elif checkpoint is not None:
        log.append(
            request_id="phase_run",
            kind="phase",
            status="completed",
            payload={
                "phase": "run",
                "elapsed_ms": 1.0,
                "limit_reached": None,
                "checkpoint_seq": checkpoint,
            },
        )
    return log


@pytest.mark.asyncio
async def test_rebuild_hook_sees_the_checkpoint_not_the_seed(tmp_path: Path) -> None:
    evidence_root = tmp_path / "run"
    box = evidence_root / AGENT_BOX_REL
    workspace = box / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "note.txt").write_text("from-checkpoint\n", encoding="utf-8")
    CheckpointStore(evidence_root, box).capture(4)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "note.txt").write_text("from-seed\n", encoding="utf-8")
    order: list[str] = []
    host = _Host(box)
    ctx = _ctx(tmp_path, host, _log(tmp_path, system=True, checkpoint=4), _graph(order))
    ctx.seed_dir = seed
    ctx.recovery_rebuild = True
    await environment.run(ctx)
    assert host.execs and host.execs[0][1] == "from-seed\n"
    assert order[-1] == "from-checkpoint\n"
    assert order[:3] == [BEFORE_ENVIRONMENT, AFTER_ENVIRONMENT_READY, ENVIRONMENT_SETUP]


@pytest.mark.asyncio
async def test_first_run_keeps_the_hook_order(tmp_path: Path) -> None:
    order: list[str] = []
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    host = _Host(evidence.path(AGENT_BOX_REL))
    ctx = _ctx(tmp_path, host, ActivityLog.open(tmp_path / "activity.jsonl"), _graph(order))
    await environment.run(ctx)
    assert order == [
        BEFORE_ENVIRONMENT,
        AFTER_ENVIRONMENT_READY,
        ENVIRONMENT_SETUP,
        "",
    ]


@pytest.mark.asyncio
async def test_mismatched_system_effect_writes_recovery_rebuild_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    host = _Host(evidence.path(AGENT_BOX_REL), exit_code=1)
    log = _log(tmp_path, system=True, checkpoint=None)
    ctx = _ctx(tmp_path, host, log, ExtensionGraph(profile_id="solver"))
    ctx.recovery_rebuild = True
    with pytest.raises(RecordedError) as caught:
        await environment.run(ctx)
    assert caught.value.error_title == "recovery_rebuild_failed"

    async def _env(inner: AttemptCtx) -> None:
        raise RecordedError("recovery_rebuild_failed", "exited 1")

    async def _phase(name: str, inner: AttemptCtx) -> None:
        inner.phase = name

    monkeypatch.setattr(environment, "run", _env)
    monkeypatch.setattr(evaluate, "run", lambda inner: _phase("evaluate", inner))
    monkeypatch.setattr(record, "run", lambda inner: _phase("record", inner))
    monkeypatch.setattr(cleanup, "run", lambda inner: _phase("cleanup", inner))
    failed = _ctx(tmp_path / "second", host, log, ExtensionGraph(profile_id="solver"))
    await run_attempt(failed)
    error = _error_fact(failed)
    assert error is not None
    assert error["title"] == "recovery_rebuild_failed"
    result = bind_result(
        evaluator_raw=None,
        kind="local",
        evidence_path=failed.evidence.locator,
        error=error,
    )
    write_attempt_result(failed.evidence.root, result.as_dict())
    document = json.loads((failed.evidence.root / "result.json").read_text(encoding="utf-8"))
    assert document["status"] == "ERROR"
    assert document["error"]["title"] == "recovery_rebuild_failed"


def test_workspace_execute_is_not_a_system_effect(tmp_path: Path) -> None:
    assert command_system_effect("python3 aggregate.py", "/attempt/workspace") is False
    assert command_system_effect("apt-get install -y tmux", "/attempt/workspace") is True
    assert command_system_effect("apk add tmux", "/attempt/workspace") is True
    assert command_system_effect("dnf install -y tmux", "/attempt/workspace") is True
    assert command_system_effect("yum install -y tmux", "/attempt/workspace") is True
    assert command_system_effect("pip install requests", "/attempt/workspace") is True
    assert command_system_effect("npm install -g typescript", "/attempt/home") is True
    assert command_system_effect("npm install typescript", "/attempt/workspace") is False
    assert command_system_effect("python3 aggregate.py", "/usr/local") is True
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
    scope.record_tool_call_in_flight(
        "call_ws",
        "execute",
        "execute",
        {"command": "python3 aggregate.py"},
        system_effect=command_system_effect("python3 aggregate.py", "/attempt/workspace"),
    )
    scope.record_tool_call_completed("call_ws", outcome="ok", exit_code=0, content="")
    assert log.completed_system_effect_tools() == []
