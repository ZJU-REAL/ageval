"""A fatal Agent invoke raises before harness success can reach evaluate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ageval.attempt.phases import run as run_phase
from ageval.evaluation.error_record import RecordedError
from ageval.model.errors import FATAL_INVOKE_TITLE


class _Ctx:
    def __init__(self) -> None:
        self.phase = ""
        self.phase_facts: list[SimpleNamespace] = []
        self.agent_service: Any = None
        self.activity = None
        self.stopped = False
        self.replay_plan = None
        self.harvested = False

    def arm_phase_budget(self, key: str) -> None:
        del key

    def phase_budget_exhausted(self) -> bool:
        return False

    def record_fact(self, name: str, detail: dict[str, object] | None = None) -> None:
        self.phase_facts.append(SimpleNamespace(name=name, detail=dict(detail or {})))

    def note_limit_reached(self, name: str) -> None:
        self.phase_facts.append(SimpleNamespace(name="limit_reached", detail={"name": name}))

    def limit_name(self) -> str | None:
        for fact in self.phase_facts:
            if fact.name == "limit_reached":
                value = fact.detail.get("name")
                if isinstance(value, str) and value:
                    return value
        return None

    def active_elapsed_ms(self) -> int:
        return 0

    def mark_writers_stopped(self) -> None:
        self.stopped = True


def _patch(monkeypatch: pytest.MonkeyPatch, outcome: dict[str, object]) -> _Ctx:
    async def fake_emit(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_harvest(ctx: _Ctx) -> None:
        ctx.harvested = True

    async def fake_worker(_ctx: _Ctx) -> dict[str, object]:
        return outcome

    monkeypatch.setattr(run_phase, "emit", fake_emit)
    monkeypatch.setattr(run_phase, "harvest_workspace_artifacts", fake_harvest)
    monkeypatch.setattr(run_phase, "_run_task_entry", fake_worker)
    return _Ctx()


def _with_fatal(ctx: _Ctx) -> _Ctx:
    ctx.agent_service = SimpleNamespace(
        service=SimpleNamespace(
            fatal_error=None,
            fatal_invoke=(
                "ModelConfigError",
                "ModelConfigError:chat_http_403:insufficient balance",
            ),
        )
    )
    return ctx


@pytest.mark.asyncio
async def test_fatal_invoke_wins_over_harness_success(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _with_fatal(
        _patch(monkeypatch, {"ok": True, "terminal": {"kind": "completed", "reason": "ok"}})
    )
    with pytest.raises(RecordedError) as raised:
        await run_phase.run(ctx)  # type: ignore[arg-type]
    assert raised.value.error_title == FATAL_INVOKE_TITLE
    assert raised.value.error_message == ("ModelConfigError:chat_http_403:insufficient balance")
    assert ctx.harvested is False
    assert ctx.stopped is True


@pytest.mark.asyncio
async def test_ordinary_failed_terminal_keeps_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _patch(
        monkeypatch,
        {"ok": True, "terminal": {"kind": "failed", "reason": "task_gave_up"}},
    )
    ctx.agent_service = SimpleNamespace(
        service=SimpleNamespace(fatal_error=None, fatal_invoke=None)
    )
    await run_phase.run(ctx)  # type: ignore[arg-type]
    assert ctx.harvested is True
