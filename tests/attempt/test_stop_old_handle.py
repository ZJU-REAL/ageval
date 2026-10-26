"""A mismatched environment is discarded, then rebuilt, even if discard fails."""

from __future__ import annotations

from collections.abc import Mapping
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
    def __init__(self, *, fail: bool = False) -> None:
        self.attaches = 0
        self.starts = 0
        self.discarded: list[dict[str, object]] = []
        self.fail = fail

    async def probe(self, handle: dict[str, object]) -> ProbeStatus:
        del handle
        return ProbeStatus(status="idle", nonce="other")

    async def attach(self, handle: dict[str, object]) -> None:
        del handle
        self.attaches += 1

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        self.starts += 1

    async def discard(self, handle: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.discarded.append(handle)


def _ctx(tmp_path: Path, host: _Host, handle: Mapping[str, object]) -> AttemptCtx:
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
    log.update_attempt_header(environment_handle=handle)
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
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
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


@pytest.mark.asyncio
async def test_cursor_mismatch_discards_then_rebuilds(tmp_path: Path) -> None:
    handle = {"container_id": "c1", "compose_project": "proj"}
    host = _Host()
    decision = await classify_environment(_ctx(tmp_path, host, handle))
    assert decision == "rebuild"
    assert host.discarded == [handle]
    assert host.attaches == 0
    assert host.starts == 0


@pytest.mark.asyncio
async def test_discard_failure_still_rebuilds(tmp_path: Path) -> None:
    host = _Host(fail=True)
    decision = await classify_environment(
        _ctx(tmp_path, host, {"container_id": "c1", "compose_project": "proj"})
    )
    assert decision == "rebuild"
    assert host.attaches == 0
