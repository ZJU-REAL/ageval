"""anthropic-http: Messages round-trip on a loopback mock; missing key fail-closed."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ageval.plugins.contrib.anthropic_http.executor import (
    AnthropicHTTPExecutor,
    anthropic_messages,
    anthropic_tools,
)
from ageval.plugins.executor_capabilities import get_capabilities


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def test_capability_matrix_is_native_tools() -> None:
    caps = get_capabilities("anthropic-http")
    assert caps is not None
    assert caps.tools == "native"
    assert caps.session == "new-only"
    assert caps.execution_mode == "api-client"
    assert caps.credential_env_names == ("ANTHROPIC_API_KEY",)


def test_missing_credential_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = AnthropicHTTPExecutor(base_url="https://api.example.invalid/v1").invoke("hi")
    assert result.ok is False
    assert result.error == "missing_credential"
    assert result.tool_calls == ()


def test_loopback_invokes_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["x-api-key"] = self.headers.get("x-api-key")
            captured["authorization"] = self.headers.get("Authorization")
            captured["version"] = self.headers.get("anthropic-version")
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {"content": [{"type": "text", "text": "ok"}]}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    try:
        result = AnthropicHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == "ok"
    assert captured.get("x-api-key") is None
    assert captured.get("authorization") is None
    assert captured.get("version") == "2023-06-01"
    assert captured["path"].endswith("/messages")
    assert captured["body"]["max_tokens"] == 4096
    assert "tools" not in captured["body"]


def test_tools_round_trip_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["path"] = self.path
            captured["x-api-key"] = self.headers.get("x-api-key")
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "find_customer",
                        "input": {"email": "alex@example.com"},
                    }
                ],
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 2,
                    "cache_creation_input_tokens": 3,
                },
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    try:
        result = AnthropicHTTPExecutor(model={"id": "mock"}, base_url=base).invoke(
            "lookup the customer",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "find_customer",
                        "description": "Find a customer",
                        "parameters": {
                            "type": "object",
                            "properties": {"email": {"type": "string"}},
                        },
                    },
                }
            ],
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.tool_calls == (
        {
            "id": "toolu_1",
            "name": "find_customer",
            "arguments": {"email": "alex@example.com"},
        },
    )
    assert result.events[0]["source"] == "anthropic-http"
    assert result.events[0]["kind"] == "tool"
    assert captured["path"].endswith("/messages")
    assert captured["x-api-key"] == "sk-ant-test"
    tool = captured["body"]["tools"][0]
    assert tool["name"] == "find_customer"
    assert tool["input_schema"]["properties"]["email"] == {"type": "string"}
    assert "function" not in tool
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 11
    assert result.usage["completion_tokens"] == 4
    assert result.usage["cached_tokens"] == 2
    extra = result.extra
    assert extra is not None
    assert extra["cache_creation_input_tokens"] == 3
    assert extra["id"] == "msg_1"


def test_system_and_tool_history_are_translated() -> None:
    system, chat = anthropic_messages(
        "ignored",
        [
            {"role": "system", "content": "Be a clerk."},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "find_customer",
                            "arguments": '{"email":"a@b.com"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"ok":true}',
            },
        ],
    )
    assert system == "Be a clerk."
    assert chat[0]["role"] == "user"
    assert chat[1]["role"] == "assistant"
    assert chat[1]["content"][0]["type"] == "tool_use"
    assert chat[1]["content"][0]["input"] == {"email": "a@b.com"}
    assert chat[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok":true}'},
        ],
    }
    catalog = anthropic_tools(
        [
            {
                "type": "function",
                "function": {"name": "find_customer", "parameters": {"type": "object"}},
            }
        ]
    )
    assert catalog == [
        {"name": "find_customer", "input_schema": {"type": "object"}},
    ]


def test_thinking_block_becomes_thought_event(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            payload = {
                "content": [
                    {"type": "thinking", "thinking": "need lookup first"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "lookup",
                        "input": {"q": "hi"},
                    },
                ]
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    collect = tmp_path / "raw"
    try:
        result = AnthropicHTTPExecutor(model={"id": "mock"}, base_url=base).invoke(
            "lookup",
            tools=[{"type": "function", "function": {"name": "lookup"}}],
            collect_dir=str(collect),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.events[0]["channel"] == "thought"
    assert result.events[0]["text"] == "need lookup first"
    assert result.events[1]["kind"] == "tool"
    dumped = json.loads((collect / "request.json").read_text(encoding="utf-8"))
    assert dumped["tools"][0]["name"] == "lookup"


def test_extra_body_and_max_tokens() -> None:
    from ageval.plugins.contrib.anthropic_http import build_anthropic_http_executor

    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            captured["version"] = self.headers.get("anthropic-version")
            payload = {"content": [{"type": "text", "text": "ok"}]}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    try:
        ex = build_anthropic_http_executor(
            model={
                "id": "claude-sonnet-4-6",
                "extra": {"thinking": {"type": "enabled", "budget_tokens": 2000}},
            },
            base_url=base,
            options={"max_tokens": 128, "anthropic_version": "2023-06-01"},
        )
        result = ex.invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert captured["body"]["max_tokens"] == 128
    assert captured["body"]["thinking"] == {"type": "enabled", "budget_tokens": 2000}
    assert captured["version"] == "2023-06-01"


def test_invalid_extra_body() -> None:
    from ageval.model import ModelConfigError
    from ageval.plugins.contrib.anthropic_http import build_anthropic_http_executor
    from ageval.plugins.errors import ExtensionMaterializeError

    with pytest.raises(ModelConfigError, match="extra_body"):
        build_anthropic_http_executor(
            model={"id": "claude-sonnet-4-6"},
            options={"extra_body": ["thinking"]},
        )
    with pytest.raises(ModelConfigError, match="model_extra_rejected"):
        build_anthropic_http_executor(
            model={"id": "claude-sonnet-4-6", "extra": {"model": "other"}},
        )
    with pytest.raises(ExtensionMaterializeError, match="anthropic_max_tokens_invalid"):
        build_anthropic_http_executor(
            model={"id": "claude-sonnet-4-6"},
            options={"max_tokens": 0},
        )
    with pytest.raises(ModelConfigError, match="model_field_unsupported"):
        build_anthropic_http_executor(
            model={"id": "claude-sonnet-4-6", "reasoning": {"effort": "high"}},
        )
