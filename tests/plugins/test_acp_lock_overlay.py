"""Lock-derived ACP Attempt-HOME overlays (no host catalog copy)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ageval.environments.protocol import HOME_PATH, ExecResult
from ageval.plugins.contrib.acp.home import write_lock_overlays
from ageval.plugins.contrib.acp.hooks import _write_lock_overlays
from ageval.plugins.contrib.acp.lock_overlay import (
    OverlayFile,
    overlays_for_entry,
    split_model,
)
from ageval.plugins.contrib.acp.registry import get_entry


def test_split_model_first_slash() -> None:
    assert split_model("zai-coding-cn/glm-5.3") == ("zai-coding-cn", "glm-5.3")
    assert split_model("glm-5.3") == (None, "glm-5.3")
    assert split_model("openai/dashscope/qwen") == ("openai", "dashscope/qwen")


def _job(
    *, entry: str, model: str, api_key: str = "ZHIPU_API_KEY", base_url: str | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "executor": "acp",
        "model": {"id": model},
        "api_key": api_key,
        "options": {"entry": entry},
        "extensions": [{"plugin": "acp"}, {"plugin": "docker"}],
    }
    if base_url is not None:
        row["base_url"] = base_url
    return {"agent_profiles": {"solver": row}}


def test_pi_overlay_builtin_provider_no_host_secret() -> None:
    files = overlays_for_entry("pi", _job(entry="pi", model="zai-coding-cn/glm-5.3"))
    dests = {item.dest: item.payload for item in files}
    assert ".pi/agent/models.json" in dests
    assert ".pi/agent/settings.json" in dests
    providers = dests[".pi/agent/models.json"]["providers"]["zai-coding-cn"]
    assert providers["apiKey"] == "$ZHIPU_API_KEY"
    assert providers["models"] == [{"id": "glm-5.3", "name": "glm-5.3"}]
    assert "baseUrl" not in providers
    assert dests[".pi/agent/settings.json"] == {
        "defaultProvider": "zai-coding-cn",
        "defaultModel": "glm-5.3",
    }
    dumped = str(dests)
    assert "sk-" not in dumped


def test_pi_overlay_custom_base_url() -> None:
    files = overlays_for_entry(
        "pi",
        _job(
            entry="pi",
            model="litellm/glm-5.3",
            api_key="litellm_api_key",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        ),
    )
    providers = next(item.payload for item in files if item.dest.endswith("models.json"))[
        "providers"
    ]["litellm"]
    assert providers["baseUrl"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert providers["api"] == "openai-completions"
    assert providers["apiKey"] == "$litellm_api_key"


def test_entry_default_writes_nothing() -> None:
    assert overlays_for_entry("pi", _job(entry="pi", model="entry-default")) == []
    assert overlays_for_entry("opencode", _job(entry="opencode", model="entry-default")) == []


def test_opencode_overlay_model_and_locator() -> None:
    files = overlays_for_entry(
        "opencode",
        _job(
            entry="opencode",
            model="litellm/glm-5.3",
            api_key="litellm_api_key",
            base_url="https://example.invalid/v1",
        ),
    )
    assert len(files) == 1
    assert files[0].dest == ".config/opencode/opencode.json"
    payload = files[0].payload
    assert payload["model"] == "litellm/glm-5.3"
    provider = payload["provider"]["litellm"]
    assert provider["options"]["apiKey"] == "{env:litellm_api_key}"
    assert provider["options"]["baseURL"] == "https://example.invalid/v1"
    assert "glm-5.3" in provider["models"]


def test_codex_overlay_toml_with_provider() -> None:
    files = overlays_for_entry(
        "codex",
        _job(
            entry="codex",
            model="litellm/glm-5.3",
            api_key="OPENAI_API_KEY",
            base_url="https://example.invalid/v1",
        ),
    )
    dests = {item.dest: item for item in files}
    assert ".codex/models.json" in dests
    assert ".codex/config.toml" in dests
    catalog = dests[".codex/models.json"].payload
    assert catalog["models"][0]["slug"] == "glm-5.3"
    assert catalog["models"][0]["base_instructions"] == ""
    text = dests[".codex/config.toml"].payload
    assert 'model = "glm-5.3"' in text
    assert "model_catalog_json" in text
    assert 'sandbox_mode = "danger-full-access"' in text
    assert 'approval_policy = "never"' in text
    assert 'model_provider = "litellm"' in text
    assert 'base_url = "https://example.invalid/v1"' in text
    assert 'wire_api = "responses"' in text
    assert 'env_key = "OPENAI_API_KEY"' in text


def test_codex_overlay_resolves_locator_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("litellm_base_url", "https://gateway.example/v1")
    files = overlays_for_entry(
        "codex",
        _job(
            entry="codex",
            model="litellm/glm-5.3",
            api_key="OPENAI_API_KEY",
            base_url="litellm_base_url",
        ),
    )
    text = next(item.payload for item in files if item.dest == ".codex/config.toml")
    assert isinstance(text, str)
    assert 'base_url = "https://gateway.example/v1"' in text


def test_codex_overlay_omits_unset_locator_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("litellm_base_url", raising=False)
    files = overlays_for_entry(
        "codex",
        _job(
            entry="codex",
            model="litellm/glm-5.3",
            api_key="OPENAI_API_KEY",
            base_url="litellm_base_url",
        ),
    )
    text = next(item.payload for item in files if item.dest == ".codex/config.toml")
    assert isinstance(text, str)
    assert "base_url" not in text


def test_claude_overlay_settings_json() -> None:
    files = overlays_for_entry("claude-code", _job(entry="claude-code", model="glm-5.3"))
    assert files[0].dest == ".claude/settings.json"
    assert files[0].payload == {"model": "glm-5.3"}


def test_grok_has_no_file_overlay() -> None:
    assert overlays_for_entry("grok-build", _job(entry="grok-build", model="grok-4")) == []


def test_union_models_from_all_roles() -> None:
    job = {
        "agent_profiles": {
            "user": {
                "model": {"id": "zai-coding-cn/glm-5.3"},
                "api_key": "ZHIPU_API_KEY",
                "options": {"entry": "pi"},
            },
            "service": {
                "model": {"id": "zai-coding-cn/glm-5.2"},
                "api_key": "ZHIPU_API_KEY",
                "options": {"entry": "pi"},
            },
        }
    }
    files = overlays_for_entry("pi", job)
    models = next(item.payload for item in files if item.dest.endswith("models.json"))["providers"][
        "zai-coding-cn"
    ]["models"]
    ids = [row["id"] for row in models]
    assert ids == ["glm-5.3", "glm-5.2"]


@dataclass
class _Host:
    uploads: list[tuple[str, str]] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    async def exec(self, command, **kwargs: Any) -> ExecResult:  # noqa: ANN001
        del kwargs
        self.commands.append([str(p) for p in command])
        return ExecResult(exit_code=0, stdout="", stderr="")

    async def upload(self, source: str | Path, dest: str) -> None:
        self.uploads.append((str(source), dest))


@pytest.mark.asyncio
async def test_write_lock_overlays_uploads_under_attempt_home() -> None:
    host = _Host()
    written = await write_lock_overlays(
        host,
        [
            OverlayFile(
                dest=".pi/agent/models.json",
                payload={"providers": {}},
                kind="json",
            )
        ],
    )
    assert written == [".pi/agent/models.json"]
    assert host.uploads[0][1] == f"{HOME_PATH}/.pi/agent/models.json"
    assert any(cmd[:2] == ["mkdir", "-p"] for cmd in host.commands)


@dataclass
class _Lock:
    job_overlay: dict[str, Any]


@dataclass
class _Ctx:
    host: Any
    lock: Any
    facts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def record_fact(self, name: str, detail: dict[str, Any] | None = None) -> None:
        self.facts.append((name, dict(detail or {})))


@pytest.mark.asyncio
async def test_hook_writes_pi_overlay_from_lock() -> None:
    host = _Host()
    ctx = _Ctx(
        host=host,
        lock=_Lock(job_overlay=_job(entry="pi", model="zai-coding-cn/glm-5.3")),
    )
    desc = get_entry("pi")
    assert desc is not None
    written = await _write_lock_overlays(ctx, desc, timeout_sec=30.0)
    assert ".pi/agent/models.json" in written
    assert ".pi/agent/settings.json" in written
    assert ctx.facts[0][0] == "acp_lock_overlay_written"
    dests = {dest for _, dest in host.uploads}
    assert f"{HOME_PATH}/.pi/agent/models.json" in dests


@pytest.mark.asyncio
async def test_hook_skips_without_lock() -> None:
    host = _Host()
    ctx = _Ctx(host=host, lock=None)
    desc = get_entry("pi")
    assert desc is not None
    assert await _write_lock_overlays(ctx, desc, timeout_sec=30.0) == []
    assert host.uploads == []
