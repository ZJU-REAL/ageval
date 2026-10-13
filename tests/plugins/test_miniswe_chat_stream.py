"""miniswe Chat Completions stream by default. Offline loopback only."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ageval.plugins.errors import ExtensionMaterializeError

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.factory import MinisweExecutorSPI  # noqa: E402
from miniswe_plugin.llm_client import (  # noqa: E402
    _chat_stream_enabled,
    assemble_chat_completion_from_stream,
    post_chat_completions,
)


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def _executor(**kwargs: Any) -> MinisweExecutorSPI:
    host = object()
    return MinisweExecutorSPI(
        host=host,
        placement=object(),
        model={"id": "openai/m"},
        **kwargs,
    )


def test_assemble_folds_tool_call_deltas_usage_and_reasoning() -> None:
    chunks = [
        {
            "id": "chatcmpl-1",
            "created": 1,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "look"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": "step",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "ba", "arguments": '{"c'},
                            }
                        ],
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": " two",
                        "tool_calls": [
                            {"index": 0, "function": {"name": "sh", "arguments": 'md":"ls"}'}}
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
    ]
    data = assemble_chat_completion_from_stream(chunks)
    message = data["choices"][0]["message"]
    assert message["content"] == "look"
    assert message["reasoning_content"] == "step two"
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    tool = message["tool_calls"][0]
    assert tool["id"] == "call_1"
    assert tool["function"]["name"] == "bash"
    assert tool["function"]["arguments"] == '{"cmd":"ls"}'
    assert data["usage"]["total_tokens"] == 7


def test_chat_stream_enabled_defaults_on_and_env_can_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGEVAL_MINISWE_CHAT_STREAM", raising=False)
    assert _chat_stream_enabled(None) is True
    assert _chat_stream_enabled(False) is False
    assert _chat_stream_enabled(True) is True
    monkeypatch.setenv("AGEVAL_MINISWE_CHAT_STREAM", "0")
    assert _chat_stream_enabled(None) is False
    assert _chat_stream_enabled(True) is True
    monkeypatch.setenv("AGEVAL_MINISWE_CHAT_STREAM", "off")
    assert _chat_stream_enabled(None) is False


def test_options_stream_parsing() -> None:
    assert _executor().stream is True
    assert _executor(options={"stream": False}).stream is False
    assert _executor(options={"stream": "off"}).stream is False
    assert _executor(options={"stream": "yes"}).stream is True
    responses = MinisweExecutorSPI(
        host=object(),
        placement=object(),
        model={"id": "openai/m", "api": "responses"},
    )
    assert responses.stream is None
    with pytest.raises(ExtensionMaterializeError, match="miniswe_stream_invalid"):
        _executor(options={"stream": "maybe"})


def _require_chat_http() -> None:
    """Default CI does not install the miniswe extra, so httpx and openai are absent."""
    pytest.importorskip("httpx")
    pytest.importorskip("openai")


def _sse(events: list[dict[str, Any] | str]) -> str:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(f"data: {event}")
        else:
            lines.append("data: " + json.dumps(event, separators=(",", ":")))
    lines.append("")
    return "\n".join(lines)


def test_default_stream_round_trip_on_loopback(capsys: pytest.CaptureFixture[str]) -> None:
    _require_chat_http()
    captured: dict[str, Any] = {}
    sse = _sse(
        [
            {
                "id": "chatcmpl-1",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": ""},
                                }
                            ],
                        },
                    }
                ],
            },
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [{"index": 0, "function": {"arguments": '{"cmd":"ls"}'}}]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
            "[DONE]",
        ]
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            raw = sse.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    try:
        result = post_chat_completions(
            api_base=base,
            api_key=None,
            model="openai/m",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        server.shutdown()
        server.server_close()

    captured_io = capsys.readouterr()
    assert captured_io.out == ""
    assert "miniswe_chat_stream_ttfb:" in captured_io.err
    assert captured["path"] == "/v1/chat/completions"
    assert captured["body"]["stream"] is True
    assert captured["body"]["stream_options"]["include_usage"] is True
    assert captured["body"]["model"] == "m"
    message = result.choices[0].message
    assert message.tool_calls is not None
    assert message.tool_calls[0].function.name == "bash"
    assert message.tool_calls[0].function.arguments == '{"cmd":"ls"}'
    assert result.usage is not None
    assert result.usage.total_tokens == 3


def test_stream_false_posts_one_json_body(capsys: pytest.CaptureFixture[str]) -> None:
    _require_chat_http()
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "id": "chatcmpl-json",
                "object": "chat.completion",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
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
        result = post_chat_completions(
            api_base=base,
            api_key=None,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    captured_io = capsys.readouterr()
    assert captured_io.out == ""
    assert "miniswe_chat_stream_ttfb:" not in captured_io.err
    assert "stream" not in captured["body"]
    assert result.choices[0].message.content == "ok"


def test_env_disables_default_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _require_chat_http()
    monkeypatch.setenv("AGEVAL_MINISWE_CHAT_STREAM", "0")
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "id": "chatcmpl-json",
                "object": "chat.completion",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "plain"},
                    }
                ],
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
        result = post_chat_completions(
            api_base=base,
            api_key=None,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        server.shutdown()
        server.server_close()

    assert "stream" not in captured["body"]
    assert result.choices[0].message.content == "plain"
    assert capsys.readouterr().out == ""
