"""miniswe retries the current model query and does not run the package retry loop."""

from __future__ import annotations

import os
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.factory import MinisweExecutorSPI  # noqa: E402
from miniswe_plugin.stall import (  # noqa: E402
    StallExhausted,
    disable_package_model_retry,
    wait_excluding_stall,
    wrap_model_query,
)

from ageval.plugins.errors import ExtensionMaterializeError  # noqa: E402
from ageval.runtime.upstream_stall import UpstreamStall, bind_stall, reset_stall  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _stall(
    budget: int, clock: _Clock | None = None
) -> tuple[UpstreamStall, _Clock, list[dict[str, Any]]]:
    clock = clock or _Clock()
    events: list[dict[str, Any]] = []
    stall = UpstreamStall(
        budget_seconds=budget,
        phase="run",
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        on_event=events.append,
        on_freeze=lambda: None,
        on_thaw=lambda: None,
        on_fact=lambda _name, _detail: None,
    )
    return stall, clock, events


def test_wrapper_retries_the_same_messages() -> None:
    stall, clock, events = _stall(3600)
    seen: list[list[dict[str, str]]] = []
    calls = {"n": 0}
    messages = [{"role": "system", "content": "keep"}]

    def query(msgs: list[dict[str, str]], **_kwargs: object) -> dict[str, str]:
        assert os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "1"
        assert msgs is messages
        seen.append(msgs)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTPError:503")
        return {"role": "assistant", "content": "ok"}

    wrapped = wrap_model_query(query, stall)
    result = wrapped(messages)
    assert result["content"] == "ok"
    assert calls["n"] == 2
    assert seen[0] is messages
    assert messages == [{"role": "system", "content": "keep"}]
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]
    assert stall.claimed is False


def test_format_error_is_not_a_stall() -> None:
    class FormatError(Exception):
        pass

    stall, clock, events = _stall(3600)

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        raise FormatError("bad actions")

    with pytest.raises(FormatError):
        wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert clock.sleeps == []
    assert events == []


def test_format_error_after_a_wait_closes_the_stall() -> None:
    class FormatError(Exception):
        pass

    stall, clock, events = _stall(3600)
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTPError:503")
        raise FormatError("bad actions")

    with pytest.raises(FormatError):
        wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert calls["n"] == 2
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]
    assert stall.episode_open is False
    assert stall.is_frozen is False


def test_spent_budget_raises_without_another_query() -> None:
    stall, clock, _events = _stall(30)
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        raise RuntimeError("HTTPError:503")

    with pytest.raises(StallExhausted):
        wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert calls["n"] == 1
    assert clock.sleeps == []


def test_disabled_stall_calls_the_query_once() -> None:
    stall, clock, events = _stall(0)
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        raise RuntimeError("HTTPError:401")

    with pytest.raises(RuntimeError, match="HTTPError:401"):
        wrap_model_query(query, stall)([])
    assert calls["n"] == 1
    assert clock.sleeps == []
    assert events == []


def test_frozen_time_does_not_consume_the_invoke_timeout() -> None:
    stall = SimpleNamespace(is_frozen=True)

    def work() -> str:
        time.sleep(0.35)
        return "done"

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(work)
        assert wait_excluding_stall(fut, stall, 0.1) == "done"
    assert time.monotonic() - started >= 0.35


def test_unfrozen_wait_still_times_out() -> None:
    from concurrent.futures import TimeoutError as FutureTimeout

    stall = SimpleNamespace(is_frozen=False)

    def work() -> None:
        time.sleep(0.4)

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(work)
        with pytest.raises(FutureTimeout):
            wait_excluding_stall(fut, stall, 0.15)


def test_package_retry_is_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minisweagent")
    import logging

    from minisweagent.models.utils.retry import retry

    monkeypatch.setenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "10")
    disable_package_model_retry()
    attempt = retry(logger=logging.getLogger("miniswe-stall-test"), abort_exceptions=[])
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise RuntimeError("HTTPError:503")

    with pytest.raises(RuntimeError, match="HTTPError:503"):
        for item in attempt:
            with item:
                boom()
    assert calls["n"] == 1


def _install_fakes(monkeypatch: pytest.MonkeyPatch, *, failures: int) -> dict[str, Any]:
    state: dict[str, Any] = {"runs": 0, "walls": [], "calls": [], "messages": None}

    class FakeModel:
        def __init__(self, **_kwargs: object) -> None:
            self.fail_remaining = failures

        def query(self, messages: list[dict[str, Any]], **_kwargs: object) -> dict[str, Any]:
            assert os.environ.get("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT") == "1"
            state["calls"].append(messages)
            state["messages"] = messages
            if self.fail_remaining:
                self.fail_remaining -= 1
                raise RuntimeError("HTTPError:503")
            return {"role": "assistant", "content": "ok", "extra": {"actions": [], "cost": 0}}

        def format_message(self, **kwargs: object) -> dict[str, object]:
            return {"role": kwargs.get("role"), "content": kwargs.get("content")}

        def format_observation_messages(self, *_args: object, **_kwargs: object) -> list[object]:
            return []

    class FakeAgent:
        def __init__(self, model: FakeModel, env: object, **kwargs: object) -> None:
            del env
            self.model = model
            self.messages: list[dict[str, Any]] = []
            self.n_calls = 0
            self.cost = 0
            state["walls"].append(kwargs.get("wall_time_limit_seconds"))

        def run(self, task: str = "") -> dict[str, str]:
            state["runs"] += 1
            self.messages = [
                {"role": "system", "content": "keep"},
                {"role": "user", "content": task},
            ]
            held = self.messages
            self.messages.append(self.model.query(self.messages))
            assert self.messages is held or self.messages[:2] == held[:2]
            assert self.messages[0]["content"] == "keep"
            return {"exit_status": "Submitted", "submission": "done"}

    for name in ("minisweagent", "minisweagent.agents", "minisweagent.models"):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, name, module)
    agents = types.ModuleType("minisweagent.agents.default")
    agents.DefaultAgent = FakeAgent  # type: ignore[attr-defined]
    models = types.ModuleType("minisweagent.models.litellm_model")
    models.LitellmModel = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "minisweagent.agents.default", agents)
    monkeypatch.setitem(sys.modules, "minisweagent.models.litellm_model", models)
    return state


def _spi(monkeypatch: pytest.MonkeyPatch) -> MinisweExecutorSPI:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    return MinisweExecutorSPI(
        host=SimpleNamespace(kind="local"),
        placement=SimpleNamespace(workdir="/attempt/workspace", user=None),
        model="openai/x",
        api_key="OPENAI_API_KEY",
        base_url="https://api.example.invalid/v1",
    )


def test_run_agent_retries_the_query_and_not_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fakes(monkeypatch, failures=1)
    stall, clock, events = _stall(3600)
    monkeypatch.setenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "10")
    token = bind_stall(stall)
    try:
        extra = _spi(monkeypatch)._run_agent("fix the bug", timeout=5)
    finally:
        reset_stall(token)
    assert extra["exit_status"] == "Submitted"
    assert state["runs"] == 1
    assert state["walls"] == [0]
    assert len(state["calls"]) == 2
    assert state["calls"][0] is state["calls"][1]
    assert state["calls"][0][0]["content"] == "keep"
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]
    assert stall.claimed is True
    assert os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "10"


def test_invoke_reports_stall_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fakes(monkeypatch, failures=5)
    stall, clock, _events = _stall(30)
    token = bind_stall(stall)
    try:
        result = _spi(monkeypatch).invoke("fix the bug", timeout=5)
    finally:
        reset_stall(token)
    assert result.ok is False
    assert result.error == "stall_exhausted"
    assert result.metadata is not None
    assert result.metadata.get("stall_exhausted") is True
    assert state["runs"] == 1
    assert len(state["calls"]) == 1
    assert clock.sleeps == []


def test_missing_credential_is_not_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    stall, _clock, events = _stall(3600)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("litellm_api_key", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    spi = MinisweExecutorSPI(
        host=SimpleNamespace(kind="local"),
        placement=SimpleNamespace(workdir="/attempt/workspace", user=None),
        model="openai/x",
        api_key=None,
        base_url="https://api.example.invalid/v1",
    )
    token = bind_stall(stall)
    try:
        with pytest.raises(ExtensionMaterializeError, match="miniswe_missing_credential"):
            spi._run_agent("ping", timeout=1)
    finally:
        reset_stall(token)
    assert stall.claimed is False
    assert events == []
