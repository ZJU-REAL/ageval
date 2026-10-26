"""A finished in-flight tool is adopted from state/last_exit.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.recover import classify_environment, write_attempt_header
from ageval.environments.protocol import ProbeStatus
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal


class _Host:
    def __init__(self, state: Path, last_exit: dict[str, object]) -> None:
        self.state_root = state
        self.reattached = False
        self.attached: list[dict[str, object]] = []
        self._status = ProbeStatus(
            status="idle",
            nonce="nce_test",
            cursor_seq=None,
            last_exit=last_exit,
        )

    async def probe(self, handle: dict[str, object]) -> ProbeStatus:
        del handle
        return self._status

    async def attach(self, handle: dict[str, object]) -> None:
        self.attached.append(dict(handle))


def _ctx(tmp_path: Path, host: _Host, log: ActivityLog) -> AttemptCtx:
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=None,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=ExtensionGraph(profile_id="solver"),
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=host,  # type: ignore[arg-type]
        evidence=AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r"),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("exit_code", "outcome"), [(0, "ok"), (7, "error")])
async def test_classify_adopts_finished_tool_output(
    tmp_path: Path, exit_code: int, outcome: str
) -> None:
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
        environment_kind="docker",
        nonce="nce_test",
    )
    log.append(
        request_id="call_9",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": "sess",
            "invoke_request_id": "req_1",
            "tool_call_id": "call_9",
            "tool_name": "execute",
            "tool_kind": "execute",
            "arguments": {"command": "echo hi"},
            "replay_safe": False,
            "system_effect": False,
            "timeout_sec": None,
            "deadline_utc": None,
        },
    )
    host = _Host(
        tmp_path / "state",
        {
            "request_id": "call_9",
            "exit_code": exit_code,
            "stdout": "hi\n",
            "stderr": "",
        },
    )
    decision = await classify_environment(_ctx(tmp_path, host, log))
    assert decision == "attached"
    assert host.attached
    completed = log.records_for(kind="tool_call", request_id="call_9")[-1]
    assert completed.status == "completed"
    assert completed.payload["outcome"] == outcome
    assert completed.payload["content"] == "hi\n"
    assert isinstance(completed.payload["checkpoint_seq"], int)
