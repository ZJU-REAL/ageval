"""A mismatched environment is stopped, then rebuilt, even if stop fails."""

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
    def __init__(self) -> None:
        self.attaches = 0
        self.starts = 0

    async def probe(self, handle: dict[str, object]) -> ProbeStatus:
        del handle
        return ProbeStatus(status="idle", nonce="other")

    async def attach(self, handle: dict[str, object]) -> None:
        del handle
        self.attaches += 1

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        self.starts += 1


def _ctx(tmp_path: Path, kind: str, handle: dict[str, object]) -> AttemptCtx:
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
        environment_kind=kind,
        nonce="nce_test",
    )
    log.update_attempt_header(environment_handle=handle, environment_kind=kind)
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
        host=_Host(),  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "handle", "target"),
    [
        ("docker", {"container_id": "c1", "compose_project": "proj"}, "_stop_docker"),
        ("e2b", {"sandbox_id": "sbx"}, "_stop_e2b"),
        ("daytona", {"sandbox_id": "day"}, "_stop_daytona"),
        ("ssh", {"host": "box.example", "container_id": "c9"}, "_stop_ssh"),
    ],
)
async def test_cursor_mismatch_stops_then_rebuilds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    handle: dict[str, object],
    target: str,
) -> None:
    import ageval.attempt.recover as recover

    seen: list[dict[str, object]] = []

    def _sync(payload: dict[str, object]) -> None:
        seen.append(payload)

    async def _async(payload: dict[str, object]) -> None:
        seen.append(payload)

    monkeypatch.setattr(recover, target, _async if target == "_stop_ssh" else _sync)
    ctx = _ctx(tmp_path, kind, handle)
    decision = await classify_environment(ctx)
    assert decision == "rebuild"
    assert seen == [handle]
    assert ctx.host.attaches == 0
    assert ctx.host.starts == 0


@pytest.mark.asyncio
async def test_stop_failure_still_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ageval.attempt.recover as recover

    def _boom(handle: dict[str, object]) -> None:
        del handle
        raise RuntimeError("down")

    monkeypatch.setattr(recover, "_stop_docker", _boom)
    ctx = _ctx(tmp_path, "docker", {"container_id": "c1", "compose_project": "proj"})
    assert await classify_environment(ctx) == "rebuild"


@pytest.mark.asyncio
async def test_ssh_without_a_container_does_not_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ageval.attempt.recover as recover

    called: list[str] = []

    async def _ssh(self, argv: list[str], *, timeout_sec: float | None) -> None:  # noqa: ANN001
        del self, timeout_sec
        called.append(" ".join(argv))

    monkeypatch.setattr(recover, "_stop_ssh", recover._stop_ssh)
    from ageval.plugins.contrib.ssh.host import SSHHost

    monkeypatch.setattr(SSHHost, "_ssh", _ssh)
    ctx = _ctx(tmp_path, "ssh", {"host": "box.example"})
    assert await classify_environment(ctx) == "rebuild"
    assert called == []
