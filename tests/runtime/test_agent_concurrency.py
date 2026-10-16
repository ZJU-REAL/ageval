"""Run-phase invoke admission: overlap, order, quota, and seal."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from tests.helpers.agent_binding import ScriptedBinder

from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.agent_result import AgentResult
from ageval.runtime.agent_service_protocol import AgentServiceServer, agent_service_client_call
from ageval.runtime.parent_agent import ParentAgentService
from ageval_sdk import Agent

ATTEMPT = "attempt_" + "b" * 16


class HoldExecutor:
    """Blocks inside invoke until released or cancelled. One instance, many sessions."""

    kind = "scripted"
    concurrent_sessions = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.holds: list[threading.Event] = []
        self.release_all = threading.Event()
        self._cancel = threading.Event()

    def prepare_invoke(self) -> None:
        self._cancel.clear()

    def cancel_invoke(self) -> None:
        self._cancel.set()
        for hold in self.holds:
            hold.set()

    def invoke(self, prompt: str, **_kwargs: Any) -> AgentResult:
        hold = threading.Event()
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.holds.append(hold)
        try:
            while (
                not hold.is_set() and not self.release_all.is_set() and not self._cancel.is_set()
            ):
                hold.wait(0.01)
        finally:
            with self._lock:
                self.active -= 1
        if self._cancel.is_set():
            return AgentResult(
                model="scripted-model",
                text="",
                structured=None,
                ok=False,
                error="invoke_cancelled",
                repeatable=False,
            )
        return AgentResult(
            model="scripted-model",
            text=prompt,
            structured={"prompt": prompt},
            ok=True,
            error=None,
        )


def _service(
    tmp_path: Path,
    executor: HoldExecutor,
    *,
    limit: int = 8,
    concurrency: int = 1,
) -> ParentAgentService:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="run_x")
    return ParentAgentService(
        attempt_id=ATTEMPT,
        binder=ScriptedBinder(executor),
        agent_invocation_limit=limit,
        agent_concurrency=concurrency,
        evidence_store=store,
        offline_env="",
    )


def _open(service: ParentAgentService, profile_id: str = "solver") -> str:
    opened = service.open_session(profile_id=profile_id)
    assert opened["ok"], opened
    return str(opened["session_id"])


def _join(thread: threading.Thread, timeout: float = 2.0) -> None:
    thread.join(timeout)
    assert not thread.is_alive(), thread.name


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met")


def test_distinct_sessions_overlap_up_to_the_cap(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, concurrency=2)
    sessions = [_open(service) for _ in range(3)]
    results: list[dict[str, Any]] = []

    def _call(session_id: str, prompt: str) -> None:
        results.append(service.invoke(session_id=session_id, prompt=prompt))

    threads = [
        threading.Thread(daemon=True, target=_call, args=(session_id, f"p{index}"))
        for index, session_id in enumerate(sessions)
    ]
    for thread in threads:
        thread.start()
    _wait_until(lambda: backend.max_active == 2 and backend.calls == 2)
    time.sleep(0.05)
    assert backend.calls == 2
    backend.holds[0].set()
    _wait_until(lambda: backend.calls == 3)
    backend.release_all.set()
    for thread in threads:
        _join(thread)
    assert backend.max_active == 2
    assert all(item["ok"] for item in results)


def test_cap_one_does_not_overlap(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, concurrency=1)
    first = _open(service)
    second = _open(service)
    threads = [
        threading.Thread(daemon=True, target=lambda: service.invoke(session_id=first, prompt="a")),
        threading.Thread(daemon=True, target=lambda: service.invoke(session_id=second, prompt="b")),
    ]
    for thread in threads:
        thread.start()
    _wait_until(lambda: backend.calls == 1 and backend.active == 1)
    time.sleep(0.05)
    assert backend.max_active == 1
    assert backend.calls == 1
    backend.release_all.set()
    for thread in threads:
        _join(thread)
    assert backend.max_active == 1
    assert backend.calls == 2


def test_same_session_invokes_stay_in_arrival_order(tmp_path: Path) -> None:
    seen: list[str] = []

    class Ordered(HoldExecutor):
        def invoke(self, prompt: str, **kwargs: Any) -> AgentResult:
            seen.append(prompt)
            return super().invoke(prompt, **kwargs)

    backend = Ordered()
    service = _service(tmp_path, backend, concurrency=4)
    session = _open(service)
    threads = [
        threading.Thread(daemon=True, 
            target=lambda prompt: service.invoke(session_id=session, prompt=prompt),
            args=(prompt,),
        )
        for prompt in ("first", "second")
    ]
    threads[0].start()
    _wait_until(lambda: backend.active == 1)
    threads[1].start()
    time.sleep(0.05)
    assert seen == ["first"]
    assert backend.max_active == 1
    backend.release_all.set()
    for thread in threads:
        _join(thread)
    assert seen == ["first", "second"]


def test_queued_cancel_does_not_spend_quota_or_call_the_executor(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, limit=2, concurrency=1)
    session = _open(service)
    first = threading.Thread(daemon=True, 
        target=lambda: service.invoke(session_id=session, prompt="run", request_id="req_run")
    )
    second_result: dict[str, Any] = {}

    def _second() -> None:
        second_result.update(
            service.invoke(session_id=session, prompt="queued", request_id="req_queued")
        )

    first.start()
    _wait_until(lambda: backend.active == 1)
    second = threading.Thread(daemon=True, target=_second)
    second.start()
    _wait_until(
        lambda: (
            "req_queued" in service._tickets and service._tickets["req_queued"].state == "queued"
        )
    )
    drained = service.cancel_request(session_id=session, request_id="req_queued")
    _join(second)
    assert drained["drained"] is True
    assert second_result["error"] == "invoke_cancelled"
    assert backend.calls == 1
    assert service.invoke_quota is not None
    assert service.invoke_quota.remaining == 1
    backend.release_all.set()
    _join(first)


def test_unsafe_executor_is_rejected_before_it_overlaps(tmp_path: Path) -> None:
    backend = HoldExecutor()
    backend.concurrent_sessions = False
    service = _service(tmp_path, backend, concurrency=4)
    first = _open(service)
    second = _open(service)
    refused: dict[str, Any] = {}
    holder = threading.Thread(
        daemon=True,
        target=lambda: service.invoke(session_id=first, prompt="hold"),
    )
    holder.start()
    _wait_until(lambda: backend.active == 1)

    def _second() -> None:
        refused.update(service.invoke(session_id=second, prompt="overlap"))

    other = threading.Thread(daemon=True, target=_second)
    other.start()
    _wait_until(lambda: refused.get("error") == "executor_not_concurrent")
    assert backend.calls == 1
    backend.release_all.set()
    _join(holder)
    _join(other)


def test_seal_drains_an_in_flight_solver_before_returning(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, concurrency=2)
    session = _open(service)
    result: dict[str, Any] = {}

    def _call() -> None:
        result.update(service.invoke(session_id=session, prompt="live"))

    worker = threading.Thread(daemon=True, target=_call)
    worker.start()
    _wait_until(lambda: backend.active == 1)
    service.seal_run()
    _join(worker)
    assert result["error"] == "invoke_cancelled"
    assert backend.calls == 1
    assert service.invoke(session_id=session, prompt="after")["error"] == "session_closed"


def test_stall_freeze_survives_another_invoke_resuming(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend)
    seen: list[bool] = []
    service.on_phase_clock = seen.append
    service._set_phase_clock_frozen(True)
    service._set_phase_clock_frozen(True)
    service._set_phase_clock_frozen(False)
    assert service._phase_clock_frozen is True
    assert seen == [True]
    service._set_phase_clock_frozen(False)
    assert service._phase_clock_frozen is False
    assert seen == [True, False]


def _intervals(service: ParentAgentService) -> list[tuple[str, str]]:
    assert service.evidence_store is not None
    found = []
    for directory in service.evidence_store.list_invocations():
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        found.append((str(meta["started_at"]), str(meta["finished_at"])))
    return found


def test_evidence_intervals_overlap_only_when_the_cap_allows(tmp_path: Path) -> None:
    class Pause(HoldExecutor):
        def invoke(self, prompt: str, **_kwargs: Any) -> AgentResult:
            time.sleep(1.3)
            return AgentResult(
                model="scripted-model",
                text=prompt,
                structured=None,
                ok=True,
                error=None,
            )

    def _run(concurrency: int) -> list[tuple[str, str]]:
        backend = Pause()
        service = _service(tmp_path / str(concurrency), backend, concurrency=concurrency)
        sessions = [_open(service), _open(service)]
        threads = [
            threading.Thread(daemon=True, 
                target=lambda sid: service.invoke(session_id=sid, prompt="p"), args=(sid,)
            )
            for sid in sessions
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            _join(thread, 5)
        return _intervals(service)

    overlapped = _run(2)
    assert len(overlapped) == 2
    assert overlapped[0][0] < overlapped[1][1]
    assert overlapped[1][0] < overlapped[0][1]
    serial = _run(1)
    assert len(serial) == 2
    ordered = sorted(serial)
    assert ordered[1][0] >= ordered[0][1]


def test_socket_dispatch_overlaps_two_clients(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, concurrency=2)
    # macOS rejects a unix socket whose path is longer than about 100 bytes.
    socket_dir = Path("/tmp") / f"ageval-conc-{os.getpid()}"
    socket_dir.mkdir(parents=True, exist_ok=True)
    server = AgentServiceServer(service, socket_dir / "agent.sock")
    server.start()
    sessions = []
    try:
        for _ in range(2):
            opened = agent_service_client_call(
                str(server.socket_path),
                {"op": "open", "profile_id": "solver"},
            )
            assert opened["ok"]
            sessions.append(opened["session_id"])
        threads = [
            threading.Thread(daemon=True, 
                target=lambda session_id, prompt: agent_service_client_call(
                    str(server.socket_path),
                    {
                        "op": "invoke",
                        "session_id": session_id,
                        "prompt": prompt,
                        "request_id": prompt,
                    },
                ),
                args=(session_id, prompt),
            )
            for session_id, prompt in zip(sessions, ("a", "b"), strict=True)
        ]
        for thread in threads:
            thread.start()
        _wait_until(lambda: backend.max_active == 2)
        backend.release_all.set()
        for thread in threads:
            _join(thread)
    finally:
        server.stop()
        shutil.rmtree(socket_dir, ignore_errors=True)


def test_sdk_invoke_does_not_block_the_task_loop(tmp_path: Path) -> None:
    backend = HoldExecutor()
    service = _service(tmp_path, backend, concurrency=2)
    socket_dir = Path("/tmp") / f"ageval-sdk-{os.getpid()}"
    socket_dir.mkdir(parents=True, exist_ok=True)
    server = AgentServiceServer(service, socket_dir / "agent.sock")
    server.start()
    os.environ["AGEVAL_AGENT_SERVICE_SOCK"] = str(server.socket_path)
    os.environ.pop("AGEVAL_OFFLINE_AGENT", None)
    try:

        async def _run() -> int:
            agent = Agent(attempt_id=ATTEMPT)
            left = agent.session("solver")
            right = agent.session("solver")
            ticks = 0

            async def _tick() -> None:
                nonlocal ticks
                while backend.max_active < 2 or backend.active > 0:
                    ticks += 1
                    await asyncio.sleep(0.02)
                    if ticks > 40:
                        return

            await asyncio.gather(
                left.invoke("left"),
                right.invoke("right"),
                _tick(),
            )
            return ticks

        # Release the holds once both SDK invokes are inside the executor.
        def _release() -> None:
            _wait_until(lambda: backend.max_active == 2)
            time.sleep(0.12)
            backend.release_all.set()

        releaser = threading.Thread(daemon=True, target=_release)
        releaser.start()
        ticks = asyncio.run(_run())
        _join(releaser)
        assert ticks >= 3
        assert service.evidence_store is not None
        dirs = service.evidence_store.list_invocations()
        assert len(dirs) == 2
        intervals = []
        for directory in dirs:
            meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            intervals.append((meta["started_at"], meta["finished_at"], meta["invocation_id"]))
        assert intervals[0][2] != intervals[1][2]
    finally:
        os.environ.pop("AGEVAL_AGENT_SERVICE_SOCK", None)
        server.stop()
        shutil.rmtree(socket_dir, ignore_errors=True)


def test_no_background_thread_survives_the_module() -> None:
    time.sleep(0.05)
    alive = [
        t.name
        for t in threading.enumerate()
        if t.is_alive() and t is not threading.main_thread()
    ]
    assert alive == []
