"""miniswe retries the current model query and does not run the package retry loop."""

from __future__ import annotations

import contextlib
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

from ageval.model.errors import FormatError, TransportStall

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
            raise TransportStall("HTTPError:503", kind="http")
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


def test_timeout_recycles_clients_before_stall_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    stall, clock, events = _stall(3600)
    recycled = {"n": 0}
    monkeypatch.setattr(
        "miniswe_plugin.stall.recycle_llm_clients",
        lambda: recycled.__setitem__("n", recycled["n"] + 1),
    )
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("litellm.Timeout: Request timed out")
        return {"role": "assistant", "content": "ok"}

    result = wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert result["content"] == "ok"
    # before-attempt + before-retry are sync; on-failure is _recycle_async (daemon).
    deadline = time.monotonic() + 1.0
    while recycled["n"] < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert recycled["n"] >= 3
    assert calls["n"] == 2
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]


def test_watchdog_times_out_a_pure_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    stall, clock, events = _stall(3600)
    recycled = {"n": 0}
    monkeypatch.setattr(
        "miniswe_plugin.stall.recycle_llm_clients",
        lambda: recycled.__setitem__("n", recycled["n"] + 1),
    )
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.45)
            return {"role": "assistant", "content": "late"}
        return {"role": "assistant", "content": "ok"}

    started = time.monotonic()
    result = wrap_model_query(query, stall, watchdog=0.15)([{"role": "user", "content": "x"}])
    elapsed = time.monotonic() - started
    assert result["content"] == "ok"
    assert calls["n"] == 2
    assert recycled["n"] >= 3
    # Must NOT block on the hung orphan thread (executor shutdown wait=False).
    assert elapsed < 1.0, elapsed
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]


def test_watchdog_kills_in_flight_ephemeral_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Future timeout must close the in-flight client=, not only LiteLLM's cache.

    Suite hang 2026-10-11: py-spy showed ``_call_with_watchdog`` waiting
    while ``_receive_response_headers`` held an ESTAB socket on an ephemeral
    OpenAI client that was never in litellm's cache — recycle was a no-op for
    that socket, so stall retried while the orphan kept the gateway busy.
    """
    from miniswe_plugin import llm_client as lc

    stall, clock, events = _stall(3600)
    killed: list[object] = []
    real_close = lc.close_llm_client

    def spy_close(client: object) -> None:
        killed.append(client)
        real_close(client)

    monkeypatch.setattr(lc, "close_llm_client", spy_close)

    class HangClient:
        pass

    hang_client = HangClient()
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            lc.register_in_flight_client(hang_client)
            try:
                time.sleep(0.45)
                return {"role": "assistant", "content": "late"}
            finally:
                lc.unregister_in_flight_client(hang_client)
        return {"role": "assistant", "content": "ok"}

    started = time.monotonic()
    result = wrap_model_query(query, stall, watchdog=0.15)([{"role": "user", "content": "x"}])
    elapsed = time.monotonic() - started
    assert result["content"] == "ok"
    assert calls["n"] == 2
    # recycle is fire-and-forget so abandon cannot block on close(); wait briefly
    deadline = time.monotonic() + 1.0
    while hang_client not in killed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert hang_client in killed
    assert elapsed < 1.0, elapsed
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]


def test_any_failure_recycles_clients_before_stall_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    stall, clock, _events = _stall(3600)
    recycled = {"n": 0}
    monkeypatch.setattr(
        "miniswe_plugin.stall.recycle_llm_clients",
        lambda: recycled.__setitem__("n", recycled["n"] + 1),
    )
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransportStall("HTTPError:503", kind="http")
        return {"role": "assistant", "content": "ok"}

    wrap_model_query(query, stall)([])
    assert recycled["n"] == 3
    assert clock.sleeps == [60.0]


def test_model_config_error_is_not_a_stall() -> None:
    from miniswe_plugin.model import ModelConfigError

    stall, clock, events = _stall(3600)

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        raise ModelConfigError("chat_http_400:bad schema")

    with pytest.raises(ModelConfigError, match="chat_http_400"):
        wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert clock.sleeps == []
    assert events == []


def test_http_429_still_stalls() -> None:
    from miniswe_plugin.llm_client import raise_for_http_status

    stall, clock, events = _stall(3600)
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise_for_http_status("chat_http", 429, "slow down")
        return {"role": "assistant", "content": "ok"}

    result = wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert result["content"] == "ok"
    assert calls["n"] == 2
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]


def test_format_error_is_not_a_stall() -> None:
    stall, clock, events = _stall(3600)

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        raise FormatError("bad actions")

    with pytest.raises(FormatError):
        wrap_model_query(query, stall)([{"role": "user", "content": "x"}])
    assert clock.sleeps == []
    assert events == []


def test_format_error_after_a_wait_closes_the_stall() -> None:
    stall, clock, events = _stall(3600)
    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransportStall("HTTPError:503", kind="http")
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
        raise TransportStall("HTTPError:503", kind="http")

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
                raise TransportStall("HTTPError:503", kind="http")
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
        model={"id": "openai/x"},
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
    assert state["walls"] == [5]
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
        model={"id": "openai/x"},
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


def test_recycle_closes_cached_openai_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    """recycle must close nested httpx clients, not only flush the dict."""
    closed: list[str] = []

    class FakeHttp:
        def close(self) -> None:
            closed.append("http")

    class FakeOpenAI:
        def __init__(self) -> None:
            self._client = FakeHttp()

        def close(self) -> None:
            closed.append("openai")

    class FakeCache:
        def __init__(self) -> None:
            self.cache_dict = {"k": FakeOpenAI()}
            self.flushed = False

        def flush_cache(self) -> None:
            self.flushed = True
            self.cache_dict.clear()

    fake_litellm = SimpleNamespace(
        in_memory_llm_clients_cache=FakeCache(),
        client_session=None,
        aclient_session=None,
    )
    monkeypatch.setitem(__import__("sys").modules, "litellm", fake_litellm)  # type: ignore[arg-type]
    # Ensure import inside recycle sees our fake
    import miniswe_plugin.llm_client as llm_client

    monkeypatch.setitem(__import__("sys").modules, "litellm", fake_litellm)  # type: ignore[arg-type]
    llm_client.recycle_llm_clients()
    assert "openai" in closed
    assert "http" in closed
    assert fake_litellm.in_memory_llm_clients_cache.flushed is True
    assert fake_litellm.in_memory_llm_clients_cache.cache_dict == {}


def test_ephemeral_client_disables_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("httpx")
    pytest.importorskip("openai")
    from miniswe_plugin.llm_client import close_llm_client, make_ephemeral_openai_client

    client = make_ephemeral_openai_client(
        api_key="sk-test", api_base="http://127.0.0.1:9/v1", timeout=30.0
    )
    try:
        http = client._client
        pool = http._transport._pool
        assert pool._max_keepalive_connections == 0
        assert client.max_retries == 0
        # default_headers / http headers carry Connection: close
        merged = dict(getattr(client, "_custom_headers", {}) or {})
        merged.update(dict(http.headers))
        assert merged.get("Connection") == "close" or merged.get("connection") == "close"
    finally:
        close_llm_client(client)


def test_bind_ephemeral_passes_client_each_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from miniswe_plugin.llm_client import bind_ephemeral_completion_client

    seen: list[object] = []

    class FakeModel:
        def _query(self, messages: object, **kwargs: object) -> dict[str, str]:
            seen.append(kwargs.get("client"))
            timeouts.append(kwargs.get("timeout"))
            return {"ok": "1"}

    model = FakeModel()
    timeouts: list[object] = []
    fake_clients: list[object] = []

    class FakeClient:
        pass

    def fake_make(**_kwargs: object) -> FakeClient:
        c = FakeClient()
        fake_clients.append(c)
        return c

    closed: list[object] = []
    monkeypatch.setattr("miniswe_plugin.llm_client.make_ephemeral_openai_client", fake_make)
    monkeypatch.setattr(
        "miniswe_plugin.llm_client.close_llm_client",
        lambda c: closed.append(c),
    )
    monkeypatch.setattr("miniswe_plugin.llm_client.recycle_llm_clients", lambda: None)
    bind_ephemeral_completion_client(model, api_key="sk", api_base="http://x/v1", timeout=10.0)
    assert model._query([], stream=False) == {"ok": "1"}
    assert model._query([], stream=False) == {"ok": "1"}
    assert len(seen) == 2
    assert seen[0] is fake_clients[0]
    assert seen[1] is fake_clients[1]
    assert seen[0] is not seen[1]
    assert closed == fake_clients
    assert timeouts == [10.0, 10.0]


def test_bind_ephemeral_pass_client_false_skips_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from miniswe_plugin.llm_client import bind_ephemeral_completion_client

    seen: list[object] = []
    timeouts: list[object] = []

    class FakeModel:
        def _query(self, messages: object, **kwargs: object) -> dict[str, str]:
            seen.append(kwargs.get("client", "NO_CLIENT"))
            timeouts.append(kwargs.get("timeout"))
            return {"ok": "1"}

    monkeypatch.setattr("miniswe_plugin.llm_client.recycle_llm_clients", lambda: None)
    model = FakeModel()
    bind_ephemeral_completion_client(
        model, api_key="sk", api_base="http://x/v1", timeout=10.0, pass_client=False
    )
    assert model._query([]) == {"ok": "1"}
    assert seen == ["NO_CLIENT"]
    assert timeouts == [10.0]


def test_wire_model_name_strips_one_provider_prefix() -> None:
    from miniswe_plugin.llm_client import wire_model_name

    assert wire_model_name("openai/openai/gpt-6-sol") == "openai/gpt-6-sol"
    assert wire_model_name("openai/DeepSeek-V4.1-Flash") == "DeepSeek-V4.1-Flash"
    assert wire_model_name("gpt-6-sol") == "gpt-6-sol"


def test_uses_openai_http_client_gates_anthropic() -> None:
    from miniswe_plugin.llm_client import uses_openai_http_client

    assert uses_openai_http_client("openai/openai/gpt-6-sol") is True
    assert uses_openai_http_client("openai/DeepSeek-V4.1-Flash") is True
    assert uses_openai_http_client("anthropic/claude-opus-5-5") is False
    assert uses_openai_http_client("bedrock/x") is False
    # After chat remap, openai/anthropic/... is safe for ephemeral client=.
    assert uses_openai_http_client("openai/anthropic/claude-opus-5-5") is True


def test_chat_model_for_openai_compat_gateway_remaps_anthropic() -> None:
    from miniswe_plugin.llm_client import chat_model_for_openai_compat_gateway

    assert (
        chat_model_for_openai_compat_gateway("anthropic/claude-opus-5-5")
        == "openai/anthropic/claude-opus-5-5"
    )
    assert chat_model_for_openai_compat_gateway("bedrock/x") == "openai/bedrock/x"
    assert chat_model_for_openai_compat_gateway("claude-opus-5-5") == "openai/claude-opus-5-5"
    # Already OpenAI-compat — DeepSeek / gpt-6-sol must not change.
    assert (
        chat_model_for_openai_compat_gateway("openai/DeepSeek-V4.1-Flash")
        == "openai/DeepSeek-V4.1-Flash"
    )
    assert (
        chat_model_for_openai_compat_gateway("openai/openai/gpt-6-sol") == "openai/openai/gpt-6-sol"
    )
    assert chat_model_for_openai_compat_gateway("azure/foo") == "azure/foo"


def test_bind_direct_responses_client_posts_curl_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minisweagent")
    from miniswe_plugin.llm_client import bind_direct_responses_client

    captured: dict[str, object] = {}

    class FakeConfig:
        model_name = "openai/openai/gpt-6-sol"
        model_kwargs = {
            "drop_params": True,
            "api_key": "sk-from-kwargs",
            "api_base": "http://kwargs/v1",
            "extra_headers": {"Connection": "close", "X-Test": "1"},
        }

    class FakeModel:
        config = FakeConfig()

        def _query(self, messages: object, **kwargs: object) -> Any:
            raise AssertionError("litellm _query must not run")

    def fake_post(**kwargs: object) -> object:
        captured.update(kwargs)
        from miniswe_plugin.llm_client import DirectResponsesResult

        return DirectResponsesResult(
            {
                "id": "resp_x",
                "object": "response",
                "output": [{"type": "function_call", "name": "bash"}],
            }
        )

    monkeypatch.setattr("miniswe_plugin.llm_client.post_responses_api", fake_post)
    monkeypatch.setattr("miniswe_plugin.llm_client.recycle_llm_clients", lambda: None)
    model = FakeModel()
    bind_direct_responses_client(model, api_key="sk-arg", api_base="http://arg/v1", timeout=12.0)
    out = model._query([{"role": "user", "content": "hi"}])
    assert getattr(out, "id", None) == "resp_x"
    assert captured["api_key"] == "sk-arg"
    assert captured["api_base"] == "http://arg/v1"
    assert captured["model"] == "openai/openai/gpt-6-sol"
    assert captured["timeout"] == 12.0
    assert captured["input"] == [{"role": "user", "content": "hi"}]
    tools = captured["tools"]
    assert isinstance(tools, list) and tools
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "bash"
    assert "function" not in tools[0]  # flat Responses schema, not chat nested


def test_bind_direct_responses_forwards_reasoning_object(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minisweagent")
    from miniswe_plugin.llm_client import DirectResponsesResult, bind_direct_responses_client

    captured: dict[str, object] = {}

    class FakeConfig:
        model_name = "openai/glm-5.2"
        model_kwargs = {
            "drop_params": True,
            "reasoning": {"summary": "auto", "effort": "high"},
            "reasoning_effort": "high",
        }

    class FakeModel:
        config = FakeConfig()

        def _query(self, messages: object, **kwargs: object) -> object:
            raise AssertionError("litellm _query must not run")

    def fake_post(**kwargs: object) -> object:
        captured.update(kwargs)
        return DirectResponsesResult({"id": "resp_x", "output": []})

    monkeypatch.setattr("miniswe_plugin.llm_client.post_responses_api", fake_post)
    monkeypatch.setattr("miniswe_plugin.llm_client.recycle_llm_clients", lambda: None)
    model = FakeModel()
    bind_direct_responses_client(model, api_key="sk", api_base="http://arg/v1", timeout=None)
    model._query([{"role": "user", "content": "hi"}])
    extra = captured["extra_body"]
    assert isinstance(extra, dict)
    assert extra["reasoning"] == {"summary": "auto", "effort": "high"}
    assert extra["reasoning_effort"] == "high"


def test_sanitize_responses_input_strips_id() -> None:
    from miniswe_plugin.llm_client import sanitize_responses_input

    raw = [
        {"role": "system", "content": "x"},
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "abc"},
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [],
            "phase": "commentary",
            "status": "completed",
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "bash",
            "arguments": "{}",
            "namespace": None,
            "status": "completed",
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
    ]
    out = sanitize_responses_input(raw)
    assert out[0] == {"role": "system", "content": "x"}
    assert "id" not in out[1] and out[1]["encrypted_content"] == "abc"
    assert "id" not in out[2] and "phase" not in out[2] and "status" not in out[2]
    assert out[3]["call_id"] == "call_1" and "id" not in out[3] and "namespace" not in out[3]
    assert out[4] == {"type": "function_call_output", "call_id": "call_1", "output": "ok"}
    assert sanitize_responses_input("hi") == "hi"


def test_close_llm_client_shutdown_unblocks_recv(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket.SHUT_RDWR must wake a thread stuck in _receive_response_headers."""
    pytest.importorskip("httpx")
    pytest.importorskip("openai")
    import socket

    import httpx
    from miniswe_plugin.llm_client import close_llm_client, register_in_flight_client
    from openai import OpenAI

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    stop = {"x": False}

    def serve() -> None:
        srv.settimeout(0.3)
        while not stop["x"]:
            try:
                conn, _ = srv.accept()
            except Exception:
                continue
            # absorb request forever
            try:
                while not stop["x"]:
                    time.sleep(0.2)
            finally:
                with contextlib.suppress(Exception):
                    conn.close()

    import threading

    threading.Thread(target=serve, daemon=True).start()
    http = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=5),
        timeout=httpx.Timeout(60.0),
        headers={"Connection": "close"},
    )
    client = OpenAI(
        api_key="sk-x",
        base_url=f"http://127.0.0.1:{port}/v1",
        http_client=http,
        timeout=60,
        max_retries=0,
    )
    register_in_flight_client(client)
    done = {"ok": False, "exc": None}

    def hung() -> None:
        try:
            client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "hi"}], timeout=60
            )
        except Exception as exc:  # noqa: BLE001
            done["exc"] = type(exc).__name__
        finally:
            done["ok"] = True

    th = threading.Thread(target=hung, daemon=True)
    th.start()
    time.sleep(0.4)
    close_llm_client(client)
    th.join(timeout=2.0)
    stop["x"] = True
    srv.close()
    assert done["ok"], "shutdown did not unblock hung recv"
    assert not th.is_alive()


def test_bind_direct_completion_client_posts_chat_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minisweagent")
    from miniswe_plugin.llm_client import bind_direct_completion_client

    captured: dict[str, object] = {}

    class FakeConfig:
        model_name = "openai/anthropic/claude-opus-5-5"
        model_kwargs = {
            "drop_params": True,
            "api_key": "sk-from-kwargs",
            "api_base": "http://kwargs/v1",
            "reasoning_effort": "none",
            "extra_headers": {"Connection": "close", "X-Test": "1"},
        }

    class FakeModel:
        config = FakeConfig()

        def _query(self, messages: object, **kwargs: object) -> Any:
            raise AssertionError("litellm _query must not run")

    def fake_post(**kwargs: object) -> object:
        captured.update(kwargs)

        class _Msg:
            def model_dump(self) -> dict[str, str]:
                return {"role": "assistant", "content": "ok"}

            tool_calls = None

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]

            def model_dump(self, mode: str = "python") -> dict[str, str]:
                return {"id": "chat_x"}

        return _Resp()

    monkeypatch.setattr("miniswe_plugin.llm_client.post_chat_completions", fake_post)
    monkeypatch.setattr("miniswe_plugin.llm_client.recycle_llm_clients", lambda: None)
    model = FakeModel()
    bind_direct_completion_client(model, api_key="sk-arg", api_base="http://arg/v1", timeout=12.0)
    out = model._query([{"role": "user", "content": "hi"}])
    assert captured["api_key"] == "sk-arg"
    assert captured["api_base"] == "http://arg/v1"
    assert captured["model"] == "openai/anthropic/claude-opus-5-5"
    assert captured["timeout"] == 12.0
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    tools = captured["tools"]
    assert isinstance(tools, list) and tools
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "bash"  # nested chat schema
    assert out.choices[0].finish_reason == "stop"


def test_future_timeout_surfaces_when_recycle_wedges(monkeypatch: pytest.MonkeyPatch) -> None:
    """TimeoutError must reach wrap_model_query even if recycle/close blocks.

    boa attempt_06c64f5f / chat attempt_1c23ff53: Future timed out but a wedged
    ``close()`` on the abandon path delayed or prevented ``upstream_stall``.
    ``_recycle_async`` + ``shutdown(wait=False)`` are the failsafe.
    """
    import miniswe_plugin.stall as stall_mod

    stall, clock, events = _stall(3600)
    gate = {"released": False}
    async_started = {"n": 0}

    def wedging_recycle() -> None:
        # Simulate close() stuck on sticky recv / pool lock (abandon path only).
        deadline = time.monotonic() + 5.0
        while not gate["released"] and time.monotonic() < deadline:
            time.sleep(0.05)

    def tracking_async() -> None:
        async_started["n"] += 1
        threading = __import__("threading")
        threading.Thread(target=wedging_recycle, name="miniswe-recycle", daemon=True).start()

    # Pre-attempt sync recycle must stay fast; only abandon uses wedging daemon.
    monkeypatch.setattr(stall_mod, "recycle_llm_clients", lambda: None)
    monkeypatch.setattr(stall_mod, "_recycle_async", tracking_async)

    calls = {"n": 0}

    def query(_messages: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.5)
            return {"role": "assistant", "content": "late"}
        return {"role": "assistant", "content": "ok"}

    started = time.monotonic()
    result = wrap_model_query(query, stall, watchdog=0.12)([{"role": "user", "content": "x"}])
    elapsed = time.monotonic() - started
    gate["released"] = True
    assert result["content"] == "ok"
    assert async_started["n"] >= 1
    # Must NOT wait on the 5s wedging recycle — daemon abandon.
    assert elapsed < 2.0, elapsed
    assert [event["outcome"] for event in events] == ["started", "wait", "resumed"]


def test_responses_blackhole_shut_rdwr_and_future_timeout() -> None:
    """responses ``post_responses_api`` blackhole: SHUT_RDWR unblocks; FutureTimeout raises."""
    pytest.importorskip("httpx")
    import json
    import socket
    import threading

    import httpx
    from miniswe_plugin.llm_client import (
        close_llm_client,
        post_responses_api,
        register_in_flight_client,
    )
    from miniswe_plugin.stall import _call_with_watchdog

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    stop = {"x": False}

    def serve() -> None:
        srv.settimeout(0.3)
        while not stop["x"]:
            try:
                conn, _ = srv.accept()
            except Exception:
                continue

            def absorb(c: socket.socket) -> None:
                try:
                    while not stop["x"]:
                        try:
                            data = c.recv(65536)
                        except Exception:
                            break
                        if not data:
                            time.sleep(0.05)
                finally:
                    with contextlib.suppress(Exception):
                        c.close()

            threading.Thread(target=absorb, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    base = f"http://127.0.0.1:{port}/v1"

    # 1) Plain close does NOT unblock sticky recv (documents the pre-SHUT_RDWR gap).
    client = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=5),
        timeout=httpx.Timeout(30.0),
        headers={"Connection": "close"},
    )
    plain = {"ok": False}

    def hung_plain() -> None:
        try:
            client.post(
                f"{base}/responses",
                headers={"Content-Type": "application/json", "Connection": "close"},
                content=json.dumps({"model": "m", "input": "hi"}).encode(),
            )
        except Exception:
            pass
        finally:
            plain["ok"] = True

    th = threading.Thread(target=hung_plain, daemon=True)
    th.start()
    time.sleep(0.35)
    client.close()
    th.join(timeout=0.4)
    assert th.is_alive() and not plain["ok"], "plain close unexpectedly unblocked recv"

    # 2) Fresh client: SHUT_RDWR via close_llm_client MUST unblock (do not plain-close first —
    # plain close drops pool._connections so a later SHUT_RDWR cannot find the sock).
    client2 = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=5),
        timeout=httpx.Timeout(30.0),
        headers={"Connection": "close"},
    )
    register_in_flight_client(client2)
    shut = {"ok": False}

    def hung_shut() -> None:
        try:
            client2.post(
                f"{base}/responses",
                headers={"Content-Type": "application/json", "Connection": "close"},
                content=json.dumps({"model": "m", "input": "hi"}).encode(),
            )
        except Exception:
            pass
        finally:
            shut["ok"] = True

    th2 = threading.Thread(target=hung_shut, daemon=True)
    th2.start()
    time.sleep(0.35)
    close_llm_client(client2)
    th2.join(timeout=2.0)
    assert not th2.is_alive() and shut["ok"], "SHUT_RDWR did not unblock responses recv"

    # 2) FutureTimeout on post_responses_api (long httpx timeout, short watchdog).
    def query(messages: object, **_kwargs: object) -> object:
        return post_responses_api(
            api_base=base,
            api_key="sk-x",
            model="openai/gpt-6-sol",
            input=messages,
            tools=None,
            timeout=30.0,
        )

    started = time.monotonic()
    raised: Exception | None = None
    try:
        _call_with_watchdog(query, [{"role": "user", "content": "hi"}], {}, 0.5)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    elapsed = time.monotonic() - started
    stop["x"] = True
    srv.close()
    assert raised is not None and type(raised).__name__ == "TimeoutError", raised
    assert "miniswe_watchdog" in str(raised)
    assert 0.4 <= elapsed < 2.0, elapsed


def test_watchdog_fires_while_stall_frozen(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stall freeze / wait_excluding_stall must not disable the Future watchdog.

    attempt_18601e06 facts had a request-timeout abort but the suite log omitted
    the reason, so freeze looked like it swallowed the abort. The diagnostic
    goes to stderr.
    """
    from miniswe_plugin.stall import _call_with_watchdog

    stall, _clock, _events = _stall(3600)
    assert stall.note_failure("prior_hang")
    assert stall.is_frozen

    def hang(_messages: object, **_kwargs: object) -> dict[str, str]:
        time.sleep(2.0)
        return {"role": "assistant", "content": "late"}

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="miniswe_watchdog:0.2"):
        _call_with_watchdog(hang, [{"role": "user", "content": "x"}], {}, 0.2)
    elapsed = time.monotonic() - started
    assert stall.is_frozen
    assert 0.15 <= elapsed < 1.0, elapsed
    captured = capsys.readouterr()
    assert "miniswe_watchdog:0.2" in captured.err
    assert "miniswe_watchdog" not in captured.out


def test_watchdog_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="miniswe_watchdog_invalid"):
        wrap_model_query(lambda *_args, **_kwargs: None, None, watchdog=0)
