"""Focused AcpExecutor unit tests (fixture-free mapping + offline + #30 usage)."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import Placement
from ageval.model.usage import UsageUnavailable
from ageval.plugins.agent_result import (
    RESULT_HEALTH_NOOP_TURN,
    observational_result_health,
    parse_validated_text_structured,
)
from ageval.plugins.contrib.acp import AcpExecutor, normalize_acp_usage
from ageval.plugins.contrib.acp.config_bind import (
    find_reasoning_config_option,
    select_option_values,
)

BOX_HOME = "/attempt/home"


def _executor(**kwargs: object) -> AcpExecutor:
    """An executor bound to a local box that was never started.

    These cases exercise binding and env projection, which happen before any
    process is attached.
    """
    return AcpExecutor(
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home=BOX_HOME),
        **kwargs,  # type: ignore[arg-type]
    )


def test_validated_text_structured_policy() -> None:
    assert parse_validated_text_structured('{"answer": 42}') == {"answer": 42}
    # Prose around JSON → no salvage
    assert parse_validated_text_structured('Here is {"answer": 42} done') is None
    assert parse_validated_text_structured("[1,2,3]") is None
    assert parse_validated_text_structured("") is None


def test_offline_forced() -> None:
    os.environ["AGEVAL_OFFLINE_AGENT"] = "1"
    try:
        ex = _executor(entry_id="opencode", model="entry-default")
        r = ex.invoke(
            "hi",
            timeout=5,
            tools=[{"type": "function", "function": {"name": "unused"}}],
        )
        assert r.ok is False
        assert r.error == "offline_forced"
        assert r.metadata is not None
        assert r.metadata.get("executor_kind") == "acp"
    finally:
        os.environ.pop("AGEVAL_OFFLINE_AGENT", None)


def test_child_env_takes_credentials_from_the_host_and_paths_from_the_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("HOME", "/home/u")
    monkeypatch.setenv("ZAI_API_KEY", "k-pi")
    monkeypatch.setenv("UNRELATED_SECRET", "nope")
    monkeypatch.setenv("CLOUD_TOKEN", "leak")
    env = _executor(entry_id="pi", model="entry-default")._child_env()

    assert env["ZAI_API_KEY"] == "k-pi"
    assert env["NO_BROWSER"] == "1"
    assert env["HOME"].endswith("/home"), "the attempt HOME, never the operator's"
    assert env["HOME"] != "/home/u"
    assert "PATH" not in env, "the box publishes its own PATH"
    assert "UNRELATED_SECRET" not in env
    assert "CLOUD_TOKEN" not in env


def test_child_env_projects_api_key_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("HOME", "/h")
    for name in (
        "ZAI_API_KEY",
        "ZAI_CODING_CN_API_KEY",
        "ZHIPU_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MY_LOCATOR", "secret-glm")
    ex = _executor(
        entry_id="pi",
        model="entry-default",
        api_key_env="MY_LOCATOR",
        base_url="https://example.test/v1",
    )
    env = ex._child_env()
    assert env["MY_LOCATOR"] == "secret-glm"
    assert env["ZAI_API_KEY"] == "secret-glm"
    assert env["ANTHROPIC_BASE_URL"] == "https://example.test/v1"
    assert env["OPENAI_BASE_URL"] == "https://example.test/v1"


def test_child_env_pins_claude_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("MY_LOCATOR", "sk-claude")
    ex = _executor(
        entry_id="claude-code",
        model="glm-5.3",
        api_key_env="MY_LOCATOR",
        base_url="https://open.bigmodel.cn/api/anthropic",
    )
    env = ex._child_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-claude"
    assert env["ANTHROPIC_MODEL"] == "glm-5.3"
    assert env["ANTHROPIC_BASE_URL"] == "https://open.bigmodel.cn/api/anthropic"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "glm-5.3"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "glm-5.3"


def test_child_env_codex_full_access_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    env = _executor(entry_id="codex", model="openrouter/z-ai/glm-4.7")._child_env()
    assert env["INITIAL_AGENT_MODE"] == "agent-full-access"


def _clear_acp_cred_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ZAI_API_KEY",
        "ZAI_CODING_CN_API_KEY",
        "ZHIPU_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "XAI_API_KEY",
        "OPENCODE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_result_health_noop_turn() -> None:
    assert (
        observational_result_health(ok=True, usage=None, actual_model=None, events=())
        == RESULT_HEALTH_NOOP_TURN
    )
    assert (
        observational_result_health(
            ok=True, usage={"input_tokens": 1}, actual_model=None, events=()
        )
        is None
    )
    assert observational_result_health(ok=True, usage=None, actual_model="gpt", events=()) is None
    assert (
        observational_result_health(
            ok=True,
            usage=None,
            actual_model=None,
            events=({"kind": "tool", "phase": "start"},),
        )
        is None
    )
    ex = _executor(entry_id="pi", model="entry-default")
    ex._actual_model = None
    result = ex._result(text="pi v0.83.0 banner", ok=True, error=None, stop="end_turn")
    assert result.ok is True
    assert isinstance(result.usage, UsageUnavailable)
    assert result.usage.reason == "not_reported"
    assert not result.usage
    assert result.metadata is not None
    assert result.metadata["result_health"] == RESULT_HEALTH_NOOP_TURN
    assert result.metadata["actual_model"] is None


def test_unknown_entry_raises() -> None:
    try:
        _executor(entry_id="not-an-entry", model="x")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_normalize_acp_usage_dual_source_merge() -> None:
    """PromptResponse tokens + UsageUpdate context/cost merge without used→tokens."""
    usage, extra = normalize_acp_usage(
        prompt_usage={
            "inputTokens": 11433,
            "outputTokens": 140,
            "totalTokens": 11573,
            "thoughtTokens": 124,
            "cachedReadTokens": 8576,
            "cachedWriteTokens": 0,
        },
        usage_update={
            "used": 15925,
            "size": 1_000_000,
            "cost": {"amount": 0.012, "currency": "USD"},
            "sessionUpdate": "usage_update",
        },
    )
    assert usage is not None
    assert extra is not None
    assert usage["prompt_tokens"] == 11433
    assert usage["completion_tokens"] == 140
    assert usage["cached_tokens"] == 8576
    assert usage["cost_usd"] == 0.012
    assert extra["total_tokens"] == 11573
    assert extra["thought_tokens"] == 124
    assert extra["cached_read_tokens"] == 8576
    assert extra["cached_write_tokens"] == 0
    assert extra["context"] == {"used": 15925, "size": 1_000_000}
    assert extra["sources"] == {"prompt_usage": True, "usage_update": True}
    assert "extra" not in usage
    assert "uncached_input_tokens" not in usage
    assert "input_tokens" not in usage
    assert "used" not in extra
    assert usage["prompt_tokens"] != extra["context"]["used"]


def test_normalize_acp_usage_only_usage_update() -> None:
    usage, extra = normalize_acp_usage(
        prompt_usage=None,
        usage_update={"used": 100, "size": 1000, "cost": {"amount": 0.0, "currency": "USD"}},
    )
    assert usage is not None
    assert extra is not None
    assert "prompt_tokens" not in usage
    assert "completion_tokens" not in usage
    assert usage["cost_usd"] == 0.0
    assert extra["context"] == {"used": 100, "size": 1000}
    assert extra["sources"] == {"prompt_usage": False, "usage_update": True}


def test_normalize_acp_usage_only_prompt_usage_snake() -> None:
    usage, extra = normalize_acp_usage(
        prompt_usage={
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_read_tokens": 8,
        },
        usage_update=None,
    )
    assert usage is not None
    assert extra is not None
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 2
    assert usage["cached_tokens"] == 8
    assert extra["total_tokens"] == 12  # derived
    assert extra["cached_read_tokens"] == 8
    assert "context" not in extra
    assert extra["sources"]["prompt_usage"] is True
    assert extra["sources"]["usage_update"] is False
    assert extra["cached_read_tokens"] / usage["prompt_tokens"] == 0.8


def test_normalize_acp_usage_empty() -> None:
    assert normalize_acp_usage(None, None) == (None, None)
    assert normalize_acp_usage({}, {}) == (None, None)


def test_find_reasoning_option_prefers_thought_level_category() -> None:
    opts = [
        {"id": "mode", "category": "mode", "options": [{"value": "ask"}]},
        {"id": "effort", "options": [{"value": "high"}]},
        {"id": "thinking", "category": "thought_level", "options": [{"value": "off"}]},
    ]
    found = find_reasoning_config_option(opts)
    assert found is not None
    assert found["id"] == "thinking"


def test_find_reasoning_option_falls_back_to_known_id() -> None:
    opts = [{"id": "reasoning_effort", "options": [{"value": "high"}]}]
    found = find_reasoning_config_option(opts)
    assert found is not None
    assert found["id"] == "reasoning_effort"


def test_select_option_values_flattens_groups() -> None:
    opt = {
        "id": "thought_level",
        "options": [
            {"group": "std", "name": "Standard", "options": [{"value": "off"}, {"value": "high"}]},
            {"value": "xhigh"},
        ],
    }
    assert select_option_values(opt) == ["off", "high", "xhigh"]


class _FakeConn:
    def __init__(self, *, after_model: list[dict[str, object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.after_model = after_model

    async def set_config_option(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        if kwargs.get("config_id") == "model" and self.after_model is not None:
            return SimpleNamespace(config_options=self.after_model)
        return SimpleNamespace(config_options=[])


def _session(*options: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(config_options=list(options))


def _model_opt(*values: str, current: str = "m1") -> dict[str, object]:
    return {
        "id": "model",
        "category": "model",
        "currentValue": current,
        "options": [{"value": v} for v in values],
    }


def _thought_opt(
    *values: str, current: str = "off", option_id: str = "thought_level"
) -> dict[str, object]:
    return {
        "id": option_id,
        "category": "thought_level",
        "currentValue": current,
        "options": [{"value": v} for v in values],
    }


def test_bind_reasoning_effort_after_model() -> None:
    ex = _executor(entry_id="pi", model="m1", reasoning_effort="high")
    conn = _FakeConn()
    ex._conn = conn
    ex._acp_session_id = "sess"
    asyncio.run(_bind(ex, _session(_model_opt("m1", "m2"), _thought_opt("off", "high"))))
    assert [c["config_id"] for c in conn.calls] == ["model", "thought_level"]
    assert conn.calls[1]["value"] == "high"
    assert ex._actual_reasoning_effort == "high"


def test_bind_reasoning_uses_options_refreshed_after_model() -> None:
    after = [_model_opt("m1"), _thought_opt("off", "xhigh", current="off")]
    ex = _executor(entry_id="pi", model="m1", reasoning_effort="high")
    conn = _FakeConn(after_model=after)
    ex._conn = conn
    ex._acp_session_id = "sess"
    # session/new advertised ``high``; after model switch only ``xhigh`` remains.
    with pytest.raises(RuntimeError, match="acp_reasoning_effort_unavailable"):
        asyncio.run(_bind(ex, _session(_model_opt("m1"), _thought_opt("off", "high"))))


def test_bind_reasoning_skips_when_already_current() -> None:
    ex = _executor(entry_id="pi", model="entry-default", reasoning_effort="high")
    conn = _FakeConn()
    ex._conn = conn
    ex._acp_session_id = "sess"
    asyncio.run(
        _bind(
            ex,
            _session(_model_opt("m1", current="m1"), _thought_opt("off", "high", current="high")),
        )
    )
    assert conn.calls == []
    assert ex._actual_reasoning_effort == "high"


def test_bind_reasoning_missing_option_fails() -> None:
    ex = _executor(entry_id="pi", model="entry-default", reasoning_effort="high")
    conn = _FakeConn()
    ex._conn = conn
    ex._acp_session_id = "sess"
    with pytest.raises(RuntimeError, match="acp_reasoning_effort_unavailable"):
        asyncio.run(_bind(ex, _session(_model_opt("m1", current="m1"))))


def test_bind_skips_reasoning_when_unset() -> None:
    ex = _executor(entry_id="pi", model="entry-default")
    conn = _FakeConn()
    ex._conn = conn
    ex._acp_session_id = "sess"
    asyncio.run(_bind(ex, _session(_model_opt("m1", current="m1"), _thought_opt("off", "high"))))
    assert conn.calls == []
    assert ex._actual_reasoning_effort is None


async def _bind(ex: AcpExecutor, session: SimpleNamespace) -> None:
    latest = await ex._bind_model(session)
    await ex._bind_reasoning_effort(latest)


def test_grok_build_argv_inserts_model_and_effort() -> None:
    from ageval.plugins.contrib.acp.entry_local import acp_stdio_argv

    assert acp_stdio_argv(
        "grok-build",
        ["grok", "agent", "stdio"],
        model="grok-4.5",
        reasoning_effort="low",
    ) == ["grok", "agent", "--model", "grok-4.5", "--reasoning-effort", "low", "stdio"]
    assert acp_stdio_argv(
        "grok-build",
        ["grok", "agent", "stdio"],
        model="entry-default",
        reasoning_effort=None,
    ) == ["grok", "agent", "stdio"]
    assert acp_stdio_argv(
        "pi",
        ["pi-acp"],
        model="grok-4.5",
        reasoning_effort="low",
    ) == ["pi-acp"]


def _grok_init(*, current: str = "grok-4.6") -> dict[str, object]:
    return {
        "_meta": {
            "modelState": {
                "currentModelId": current,
                "availableModels": [
                    {
                        "modelId": "grok-4.6",
                        "_meta": {
                            "reasoningEffort": "xhigh",
                            "reasoningEfforts": [
                                {"id": "xhigh", "value": "xhigh"},
                                {"id": "high", "value": "high"},
                                {"id": "low", "value": "low"},
                            ],
                        },
                    },
                    {
                        "modelId": "grok-4.5",
                        "_meta": {
                            "reasoningEffort": "high",
                            "reasoningEfforts": [
                                {"id": "high", "value": "high"},
                                {"id": "low", "value": "low"},
                            ],
                        },
                    },
                    {"modelId": "glm-coding", "_meta": {"agentType": "grok-build-plan"}},
                ],
            }
        }
    }


def _grok_session(*, model: str = "grok-4.6", effort: str = "xhigh") -> SimpleNamespace:
    return SimpleNamespace(
        session_id="sess",
        config_options=None,
        _meta={
            "x.ai/sessionConfig": {
                "options": [
                    {"id": "grok-4.6", "category": "model", "selected": model == "grok-4.6"},
                    {"id": "grok-4.5", "category": "model", "selected": model == "grok-4.5"},
                    {"id": "glm-coding", "category": "model", "selected": model == "glm-coding"},
                    {"id": "xhigh", "category": "mode", "selected": effort == "xhigh"},
                    {"id": "low", "category": "mode", "selected": effort == "low"},
                ]
            },
            "x.ai/sessionDetail": {"currentModelId": model},
        },
    )


def test_grok_build_records_actuals_from_meta_and_skips_set_config() -> None:
    ex = _executor(entry_id="grok-build", model="grok-4.5", reasoning_effort="low")
    conn = _FakeConn()
    ex._conn = conn
    ex._acp_session_id = "sess"
    asyncio.run(
        ex._bind_entry(
            _grok_init(current="grok-4.5"), _grok_session(model="grok-4.5", effort="low")
        )
    )
    assert conn.calls == []
    assert ex._actual_model == "grok-4.5"
    assert ex._actual_reasoning_effort == "low"


def test_grok_build_unset_effort_records_default_and_does_not_fail() -> None:
    ex = _executor(entry_id="grok-build", model="entry-default")
    asyncio.run(ex._bind_entry(_grok_init(), _grok_session()))
    assert ex._actual_model == "grok-4.6"
    assert ex._actual_reasoning_effort == "xhigh"


def test_grok_build_unknown_model_fails_closed() -> None:
    ex = _executor(entry_id="grok-build", model="not-a-model")
    with pytest.raises(RuntimeError, match="acp_model_unavailable"):
        asyncio.run(ex._bind_entry(_grok_init(), _grok_session()))


def test_grok_build_unknown_effort_fails_closed() -> None:
    ex = _executor(entry_id="grok-build", model="grok-4.5", reasoning_effort="xhigh")
    with pytest.raises(RuntimeError, match="acp_reasoning_effort_unavailable"):
        asyncio.run(
            ex._bind_entry(
                _grok_init(current="grok-4.5"), _grok_session(model="grok-4.5", effort="xhigh")
            )
        )


def test_bind_model_available_models_is_exact_not_substring() -> None:
    ex = _executor(entry_id="pi", model="gpt")
    ex._conn = _FakeConn()
    ex._acp_session_id = "sess"
    session = SimpleNamespace(
        config_options=None,
        models=SimpleNamespace(available_models=[SimpleNamespace(model_id="gpt-4.1")]),
    )
    with pytest.raises(RuntimeError, match="acp_model_unavailable"):
        asyncio.run(ex._bind_model(session))


def test_bind_model_without_surface_rejects_non_default() -> None:
    ex = _executor(entry_id="pi", model="gpt-4.1")
    ex._conn = _FakeConn()
    ex._acp_session_id = "sess"
    with pytest.raises(RuntimeError, match="acp_model_unavailable"):
        asyncio.run(ex._bind_model(SimpleNamespace(config_options=None)))


def test_grok_build_effort_on_model_without_selector_fails() -> None:
    ex = _executor(entry_id="grok-build", model="glm-coding", reasoning_effort="low")
    with pytest.raises(RuntimeError, match="acp_reasoning_effort_unavailable"):
        asyncio.run(
            ex._bind_entry(
                _grok_init(current="glm-coding"),
                _grok_session(model="glm-coding", effort="low"),
            )
        )
