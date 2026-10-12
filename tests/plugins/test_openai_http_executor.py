"""openai-http: native tools= round-trip on a loopback mock; missing key fail-closed."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ageval.plugins.contrib.openai_http.executor import OpenAIHTTPExecutor
from ageval.plugins.executor_capabilities import get_capabilities


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def test_capability_matrix_is_native_tools() -> None:
    caps = get_capabilities("openai-http")
    assert caps is not None
    assert caps.tools == "native"
    assert caps.session == "new-only"
    assert caps.execution_mode == "api-client"


def test_missing_credential_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = OpenAIHTTPExecutor(base_url="https://api.example.invalid/v1").invoke("hi")
    assert result.ok is False
    assert result.error == "missing_credential"
    assert result.tool_calls == ()


@pytest.mark.parametrize(
    "base",
    [
        "http://192.168.1.10:8000/v1",
        "http://10.0.0.1/v1",
        "http://example.com/127.0.0.1",
        "http://localhost.example.com/v1",
    ],
)
def test_non_loopback_missing_credential_fail_closed(
    monkeypatch: pytest.MonkeyPatch, base: str
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = OpenAIHTTPExecutor(base_url=base).invoke("hi")
    assert result.ok is False
    assert result.error == "missing_credential"


def test_loopback_invokes_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["authorization"] = self.headers.get("Authorization")
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
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
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.error is None
    assert result.text == "ok"
    assert captured.get("authorization") is None


def test_tools_round_trip_on_loopback() -> None:
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "find_customer",
                                        "arguments": '{"email":"alex@example.com"}',
                                    },
                                }
                            ],
                        }
                    }
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
    try:
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke(
            "lookup the customer",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "find_customer",
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
            "id": "call_1",
            "name": "find_customer",
            "arguments": {"email": "alex@example.com"},
        },
    )
    assert result.events == (
        {
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "call_1",
            "function_name": "find_customer",
            "title": "find_customer",
            "args": {"email": "alex@example.com"},
            "status": "pending",
            "source": "openai-http",
        },
    )
    assert captured["path"].endswith("/chat/completions")
    assert "tools" in captured["body"]
    assert captured["body"]["tools"][0]["function"]["name"] == "find_customer"
    dumped = json.dumps(captured["body"])
    assert "sk-" not in dumped
    assert "Bearer" not in dumped
    assert "reasoning_effort" not in captured["body"]


def test_reasoning_effort_is_posted_when_set() -> None:
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
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
        result = OpenAIHTTPExecutor(
            model={"id": "mock", "reasoning": {"effort": "high"}},
            base_url=base,
        ).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert captured["body"]["reasoning_effort"] == "high"
    assert result.metadata is not None
    assert result.metadata["locked_reasoning_effort"] == "high"
    assert result.metadata["actual_reasoning_effort"] == "high"


def test_provider_extra_merges_into_chat_body() -> None:
    from ageval.plugins.contrib.openai_http import build_openai_http_executor

    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
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
        ex = build_openai_http_executor(
            model={
                "id": "deepseek/deepseek-v4-flash-0731",
                "reasoning": {"effort": "low"},
                "extra": {"provider": {"allow_fallbacks": False}},
            },
            base_url=base,
        )
        result = ex.invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert captured["body"]["provider"] == {"allow_fallbacks": False}
    assert captured["body"]["reasoning_effort"] == "low"
    assert "reasoning" not in captured["body"]
    assert captured["body"]["model"] == "deepseek/deepseek-v4-flash-0731"


def test_flat_model_and_extra_body_are_config_errors() -> None:
    from ageval.model import ModelConfigError
    from ageval.plugins.contrib.openai_http import build_openai_http_executor

    with pytest.raises(ModelConfigError, match="model_nested_required"):
        build_openai_http_executor(model="mock")
    with pytest.raises(ModelConfigError, match="extra_body"):
        build_openai_http_executor(
            model={"id": "mock"},
            options={"extra_body": {"provider": {"allow_fallbacks": False}}},
        )
    with pytest.raises(ModelConfigError, match="model_extra_rejected"):
        build_openai_http_executor(
            model={"id": "mock", "extra": {"reasoning": {"max_tokens": 128}}},
        )


def test_reasoning_content_becomes_thought_event(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "need lookup first",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"q":"hi"}',
                                    },
                                }
                            ],
                        }
                    }
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
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke(
            "lookup",
            tools=[{"type": "function", "function": {"name": "lookup"}}],
            collect_dir=str(collect),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.text == ""
    assert result.events[0]["channel"] == "thought"
    assert result.events[0]["text"] == "need lookup first"
    assert result.events[1]["kind"] == "tool"
    dumped = json.loads((collect / "response.json").read_text(encoding="utf-8"))
    assert dumped["choices"][0]["message"]["reasoning_content"] == "need lookup first"


def test_omit_tools_keeps_content_path() -> None:
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            raw = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": '{"ok":true}'}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    try:
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hello")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.tool_calls == ()
    assert result.structured == {"ok": True}
    assert result.usage is None
    assert "tools" not in captured["body"]


def test_http_usage_maps_first_class_and_extra() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            payload = {
                "id": "chatcmpl-abc",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                    "prompt_tokens_details": {"cached_tokens": 6, "audio_tokens": 0},
                    "completion_tokens_details": {
                        "reasoning_tokens": 2,
                        "accepted_prediction_tokens": 0,
                    },
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
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 11
    assert result.usage["completion_tokens"] == 4
    assert result.usage["cached_tokens"] == 6
    extra = result.extra
    assert extra is not None
    assert extra["reasoning_tokens"] == 2
    assert extra["total_tokens"] == 15
    assert extra["id"] == "chatcmpl-abc"
    assert extra["audio_tokens"] == 0
    assert "accepted_prediction_tokens" in extra
    assert "prompt_tokens" not in extra
    assert "extra" not in result.usage


def test_http_usage_omitted_does_not_fabricate_zeros() -> None:
    from ageval.plugins.contrib.openai_http.usage import normalize_openai_http_usage

    assert normalize_openai_http_usage(None) == (None, None)
    assert normalize_openai_http_usage({}) == (None, None)
    usage, extra = normalize_openai_http_usage({"prompt_tokens": 3, "completion_tokens": 1})
    assert usage is not None
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == 1
    assert "cached_tokens" not in usage
    assert "cost_usd" not in usage
    assert "extra" not in usage
    assert extra is None


def test_responses_sends_reasoning_effort_only_nested() -> None:
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {"output_text": "ok", "output": []}
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
        result = OpenAIHTTPExecutor(
            model={
                "id": "dashscope/glm-5.2",
                "api": "responses",
                "reasoning": {"effort": "xhigh"},
            },
            base_url=base,
        ).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == "ok"
    assert captured["path"].endswith("/responses")
    assert captured["body"]["reasoning"] == {"effort": "xhigh"}
    assert "reasoning_effort" not in captured["body"]
    assert "temperature" not in captured["body"]


def test_watchdog_expiry_is_a_repeatable_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    import urllib.request

    class _Hang:
        def __enter__(self) -> object:
            time.sleep(5)
            raise TimeoutError("hung")

        def __exit__(self, *_args: object) -> bool:
            return False

    def _hang(*_args: object, **_kwargs: object) -> _Hang:
        return _Hang()

    monkeypatch.setattr(urllib.request, "urlopen", _hang)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = OpenAIHTTPExecutor(
        model={"id": "mock", "timeout": 30, "watchdog": 0.2},
        base_url="https://api.example.invalid/v1",
    ).invoke("hi", timeout=30)
    assert result.ok is False
    assert result.error is not None
    assert "openai_http_watchdog" in result.error
    assert result.repeatable is True


def _status_server(code: int) -> tuple[ThreadingHTTPServer, str, dict[str, int]]:
    hits = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            hits["n"] += 1
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            raw = json.dumps({"error": {"message": "nope", "code": code}}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    return server, base, hits


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_http_4xx_is_a_model_config_error(code: int) -> None:
    server, base, hits = _status_server(code)
    try:
        result = OpenAIHTTPExecutor(
            model={"id": "dashscope/glm-5.2", "api": "responses"}, base_url=base
        ).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()
    assert hits["n"] == 1
    assert result.ok is False
    assert result.error == f"ModelConfigError:HTTPError:{code}"
    assert result.repeatable is False
    assert (result.metadata or {}).get("error_kind") == "model_config"
    assert "nope" in str((result.metadata or {}).get("http_error_body"))


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503])
def test_http_408_429_and_5xx_stay_repeatable(code: int) -> None:
    server, base, _hits = _status_server(code)
    try:
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()
    assert result.ok is False
    assert result.error == f"HTTPError:{code}"
    assert result.repeatable is True
    assert "error_kind" not in (result.metadata or {})
