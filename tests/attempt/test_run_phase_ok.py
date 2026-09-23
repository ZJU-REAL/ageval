"""Run ends on a limit without phase_failed; other worker failures still raise."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ageval.attempt.phases import run as run_phase
from ageval.evaluation.error_record import RecordedError


class _Ctx:
    def __init__(self) -> None:
        self.phase = ""
        self.phase_facts: list[SimpleNamespace] = []
        self.agent_service = None
        self.stopped = False

    def arm_phase_budget(self, key: str) -> None:
        del key

    def record_fact(self, name: str, detail: dict[str, object] | None = None) -> None:
        self.phase_facts.append(SimpleNamespace(name=name, detail=dict(detail or {})))

    def note_limit_reached(self, name: str) -> None:
        if self.limit_name() is not None:
            return
        self.record_fact("limit_reached", {"name": name})

    def limit_name(self) -> str | None:
        for fact in self.phase_facts:
            if fact.name == "limit_reached":
                value = fact.detail.get("name")
                if isinstance(value, str) and value:
                    return value
        return None

    def mark_writers_stopped(self) -> None:
        self.stopped = True


def _patch(monkeypatch: pytest.MonkeyPatch, worker) -> _Ctx:  # noqa: ANN001
    async def fake_emit(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_harvest(_ctx: object) -> None:
        return None

    monkeypatch.setattr(run_phase, "emit", fake_emit)
    monkeypatch.setattr(run_phase, "harvest_workspace_artifacts", fake_harvest)
    monkeypatch.setattr(run_phase, "_run_task_entry", worker)
    return _Ctx()


@pytest.mark.asyncio
async def test_run_phase_raises_when_the_worker_fails_without_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_worker(_ctx: object) -> dict[str, object]:
        return {"ok": False, "error": "task_run_failed"}

    ctx = _patch(monkeypatch, fake_worker)
    with pytest.raises(RuntimeError, match="task_run_failed"):
        await run_phase.run(ctx)  # type: ignore[arg-type]
    assert ctx.stopped is True
    assert ctx.limit_name() is None


@pytest.mark.asyncio
async def test_run_clock_kill_records_wall_time_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_worker(_ctx: object) -> dict[str, object]:
        return {"ok": False, "error": "task_run_timeout"}

    ctx = _patch(monkeypatch, fake_worker)
    await run_phase.run(ctx)  # type: ignore[arg-type]
    assert ctx.limit_name() == "wall_time_seconds"
    assert ctx.stopped is True
    assert any(fact.name == "task_run" for fact in ctx.phase_facts)


@pytest.mark.asyncio
async def test_later_worker_error_after_a_limit_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_worker(_ctx: object) -> dict[str, object]:
        return {"ok": False, "error": "TimeoutExpired", "message": "sleep 1"}

    ctx = _patch(monkeypatch, fake_worker)
    ctx.note_limit_reached("agent_invocations")
    await run_phase.run(ctx)  # type: ignore[arg-type]
    assert ctx.limit_name() == "agent_invocations"
    task_run = next(fact for fact in ctx.phase_facts if fact.name == "task_run")
    assert task_run.detail["error"] == "TimeoutExpired"


@pytest.mark.asyncio
async def test_worker_envelope_keeps_title_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_worker(_ctx: object) -> dict[str, object]:
        return {
            "ok": False,
            "error": "Workspace seed missing",
            "message": "seed.txt is not a file",
            "traceback": "trace",
        }

    ctx = _patch(monkeypatch, fake_worker)
    with pytest.raises(RecordedError) as caught:
        await run_phase.run(ctx)  # type: ignore[arg-type]
    assert caught.value.error_title == "Workspace seed missing"
    assert caught.value.error_message == "seed.txt is not a file"
    task_run = next(fact for fact in ctx.phase_facts if fact.name == "task_run")
    assert task_run.detail["traceback"] == "trace"
