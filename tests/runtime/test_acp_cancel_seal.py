"""ACP cancel seals evidence when the threadsafe future is cancelled.

``run_coroutine_threadsafe`` returns a ``concurrent.futures.Future``.
``result()`` raises ``concurrent.futures.CancelledError``, an ``Exception``.
The parent seals that as ``invoke_cancelled``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from tests.helpers.agent_binding import ScriptedBinder

from ageval.evidence.export import export_trajectory
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.contrib.acp.executor import AcpExecutor
from ageval.runtime.agent_service_protocol import AgentServiceServer
from ageval.runtime.parent_agent import ParentAgentService
from ageval_sdk import Agent

ATTEMPT = "attempt_" + "c" * 16


class _AcpFutureHold:
    """Block inside ``AcpExecutor._run`` until ``cancel_invoke`` cancels the future."""

    kind = "acp"
    concurrent_sessions = True

    def __init__(self) -> None:
        executor = AcpExecutor.__new__(AcpExecutor)
        executor._inflight = None
        executor._loop = None
        executor._thread = None
        executor._conn = None
        executor._acp_session_id = None
        executor._closed = False
        executor.entry_id = "offline"
        self._acp = executor
        self.waiting = threading.Event()

    def prepare_invoke(self) -> None:
        return None

    def cancel_invoke(self) -> None:
        self._acp.cancel_invoke()

    def invoke(self, prompt: str, **kwargs: Any) -> AgentResult:
        timeout = float(kwargs.get("timeout") or 30.0)

        async def _hang() -> None:
            self.waiting.set()
            await asyncio.Event().wait()

        self._acp._run(_hang(), timeout=timeout)
        return AgentResult(
            model="scripted-model",
            text=prompt,
            structured=None,
            ok=True,
            error=None,
        )

    def close(self) -> None:
        self._acp._stop_loop()


def test_acp_future_cancel_seals_and_exports(tmp_path: Path, monkeypatch) -> None:
    backend = _AcpFutureHold()
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="run_x")
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=ScriptedBinder(backend),
        agent_invocation_limit=4,
        agent_concurrency=2,
        evidence_store=store,
        offline_env="",
    )
    service.invoke_timeout_seconds = 5
    socket_dir = Path("/tmp") / f"ageval-acp-cancel-{os.getpid()}"
    socket_dir.mkdir(parents=True, exist_ok=True)
    server = AgentServiceServer(service, socket_dir / "agent.sock")
    server.start()
    monkeypatch.setenv("AGEVAL_AGENT_SERVICE_SOCK", str(server.socket_path))
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)

    def _cancel() -> None:
        assert backend.waiting.wait(2)
        ticket = next(iter(service._tickets.values()))
        service.cancel_request(session_id=ticket.session_id, request_id=ticket.request_id)

    canceller = threading.Thread(target=_cancel, daemon=True)
    canceller.start()
    try:

        async def _invoke() -> dict[str, Any]:
            async with Agent(attempt_id=ATTEMPT).session("solver") as session:
                reply = await session.invoke("hang")
            return dict(reply)

        reply = asyncio.run(_invoke())
        canceller.join(2)
        assert not canceller.is_alive()
        assert reply["ok"] is False
        assert reply["error"] == "invoke_cancelled"
        directories = store.list_invocations()
        assert len(directories) == 1
        meta = json.loads((directories[0] / "metadata.json").read_text(encoding="utf-8"))
        assert meta["status"] == "cancelled"
        assert meta["error"] == "invoke_cancelled"
        assert meta["usage"]["unavailable"] == "not_reported"
        exported = export_trajectory(store.root, tmp_path / "export")
        assert exported.ok, exported.error
        assert exported.invocation_count == 1
    finally:
        backend.close()
        server.stop()
        shutil.rmtree(socket_dir, ignore_errors=True)
        os.environ.pop("AGEVAL_AGENT_SERVICE_SOCK", None)


def _direct_service(
    tmp_path: Path, executor: Any
) -> tuple[ParentAgentService, AttemptEvidenceStore]:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="run_x")
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=ScriptedBinder(executor),
        agent_invocation_limit=4,
        agent_concurrency=1,
        evidence_store=store,
        offline_env="",
    )
    return service, store


def test_asyncio_cancelled_error_seals_as_invoke_cancelled(tmp_path: Path) -> None:
    class _Boom:
        kind = "scripted"
        concurrent_sessions = True

        def invoke(self, prompt: str, **_kwargs: Any) -> AgentResult:
            del prompt
            raise asyncio.CancelledError()

    service, store = _direct_service(tmp_path, _Boom())
    opened = service.open_session(profile_id="solver")
    assert opened["ok"]
    reply = service.invoke(session_id=str(opened["session_id"]), prompt="hang")
    assert reply["ok"] is False
    assert reply["error"] == "invoke_cancelled"
    meta = json.loads((store.list_invocations()[0] / "metadata.json").read_text(encoding="utf-8"))
    assert meta["status"] == "cancelled"
    assert meta["usage"]["unavailable"] == "not_reported"
    exported = export_trajectory(store.root, tmp_path / "export")
    assert exported.ok, exported.error


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_process_exit_is_not_sealed_as_cancelled(
    tmp_path: Path, exc_type: type[BaseException]
) -> None:
    class _Boom:
        kind = "scripted"
        concurrent_sessions = True

        def invoke(self, prompt: str, **_kwargs: Any) -> AgentResult:
            del prompt
            raise exc_type()

    service, _store = _direct_service(tmp_path, _Boom())
    opened = service.open_session(profile_id="solver")
    assert opened["ok"]
    with pytest.raises(exc_type):
        service.invoke(session_id=str(opened["session_id"]), prompt="hang")
