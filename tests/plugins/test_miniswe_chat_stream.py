"""miniswe Chat Completions stream by default. Offline loopback only."""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ageval.model.errors import TransportStall
from ageval.plugins.errors import ExtensionMaterializeError

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.factory import MinisweExecutorSPI  # noqa: E402
from miniswe_plugin.llm_client import (  # noqa: E402
    _chat_stream_enabled,
    _chunk_resets_content_idle,
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


def test_max_tokens_is_on_the_chat_body(capsys: pytest.CaptureFixture[str]) -> None:
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
            extra_body={"max_tokens": 4096, "drop_params": True},
            stream=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert capsys.readouterr().out == ""
    assert captured["body"]["max_tokens"] == 4096
    assert "drop_params" not in captured["body"]
    assert "stream" not in captured["body"]
    assert result.choices[0].message.content == "ok"


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


def test_recorded_actions_are_assistant_tool_calls_on_the_wire(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    recorded = {
        "role": "assistant",
        "content": "run",
        "extra": {
            "actions": [
                {"command": "echo one", "tool_call_id": "toolu_a"},
                {"command": "echo two", "tool_call_id": "toolu_b"},
            ]
        },
    }
    messages = [
        {"role": "user", "content": "go"},
        recorded,
        {"role": "tool", "tool_call_id": "toolu_a", "content": "one\n"},
        {"role": "tool", "tool_call_id": "toolu_b", "content": "two\n"},
    ]
    server, base = _serve(Handler)
    try:
        post_chat_completions(
            api_base=base,
            api_key=None,
            model="m",
            messages=messages,
            stream=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert capsys.readouterr().out == ""
    body = captured["body"]["messages"]
    assert [item["role"] for item in body] == ["user", "assistant", "tool", "tool"]
    assert "extra" not in body[1]
    assert body[1]["tool_calls"] == [
        {
            "id": "toolu_a",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo one"}'},
        },
        {
            "id": "toolu_b",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo two"}'},
        },
    ]
    assert body[-1]["tool_call_id"] == "toolu_b"
    assert "tool_calls" not in recorded
    assert recorded["role"] == "assistant"


def test_only_content_reasoning_and_tool_fragments_reset_content_idle() -> None:
    assert _chunk_resets_content_idle({"choices": [{"delta": {"content": "x"}}]})
    assert _chunk_resets_content_idle({"choices": [{"delta": {"content": " "}}]})
    assert _chunk_resets_content_idle({"choices": [{"delta": {"reasoning": "x"}}]})
    assert _chunk_resets_content_idle({"choices": [{"delta": {"reasoning_content": "x"}}]})
    assert _chunk_resets_content_idle(
        {"choices": [{"delta": {"thinking_blocks": [{"thinking": "x"}]}}]}
    )
    assert _chunk_resets_content_idle(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1"}]}}]}
    )
    assert _chunk_resets_content_idle(
        {"choices": [{"delta": {"tool_calls": [{"function": {"name": "bash"}}]}}]}
    )
    assert _chunk_resets_content_idle(
        {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "{"}}]}}]}
    )
    assert not _chunk_resets_content_idle({"choices": []})
    assert not _chunk_resets_content_idle({"choices": [{"delta": {}}]})
    assert not _chunk_resets_content_idle({"choices": [{"delta": {"content": ""}}]})
    assert not _chunk_resets_content_idle({"choices": [{"delta": {"role": "assistant"}}]})
    assert not _chunk_resets_content_idle(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "type": "function"}]}}]}
    )
    assert not _chunk_resets_content_idle({"usage": {"total_tokens": 1}})
    assert not _chunk_resets_content_idle(
        {"choices": [], "usage": {"prompt_tokens": 1, "total_tokens": 1}}
    )


def _data_frame(payload: Any) -> bytes:
    text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return f"data: {text}\n\n".encode()


_PING = b": ping\n\n"


def _scripted_stream(frames: list[tuple[float, bytes]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for delay, frame in frames:
                    if delay > 0:
                        time.sleep(delay)
                    self.wfile.write(frame)
                    self.wfile.flush()
            except OSError:
                return

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    return Handler


def _keepalive(seconds: float, step: float = 0.05) -> list[tuple[float, bytes]]:
    frames = (
        _PING,
        _data_frame({"choices": []}),
        _data_frame({"choices": [{"delta": {}}]}),
        _data_frame({"choices": [], "usage": {"total_tokens": 1}}),
        b"\n",
    )
    script: list[tuple[float, bytes]] = []
    elapsed = 0.0
    index = 0
    while elapsed < seconds:
        script.append((step, frames[index % len(frames)]))
        elapsed += step
        index += 1
    return script


def test_keepalive_and_empty_frames_do_not_extend_content_idle(tmp_path: Path) -> None:
    _require_chat_http()
    server, base = _serve(_scripted_stream(_keepalive(3.0)))
    started = time.perf_counter()
    try:
        with pytest.raises(TransportStall, match="chat_http_content_idle") as caught:
            post_chat_completions(
                api_base=base,
                api_key=None,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                timeout=0.5,
                sse_dump_dir=str(tmp_path),
            )
        elapsed = time.perf_counter() - started
    finally:
        server.shutdown()
        server.server_close()

    assert elapsed < 1.3
    assert caught.value.kind == "timeout"
    dumps = list((tmp_path / "miniswe-sse-failures").glob("*.sse.txt"))
    assert len(dumps) == 1
    assert dumps[0].name.endswith("-content_idle.sse.txt")
    assert ": ping" in dumps[0].read_text(encoding="utf-8")


def test_ping_after_token_does_not_buy_another_read_timeout(tmp_path: Path) -> None:
    """A late keepalive must not move the deadline out by another full read timeout."""
    _require_chat_http()
    token = _data_frame({"choices": [{"delta": {"content": "token"}}]})
    # timeout is 1.0s. The ping at 0.7s would push an httpx read timeout to ~1.7s.
    script = [(0.0, token), (0.7, _PING), (3.0, b": late\n\n")]
    server, base = _serve(_scripted_stream(script))
    started = time.perf_counter()
    try:
        with pytest.raises(TransportStall, match="chat_http_content_idle") as caught:
            post_chat_completions(
                api_base=base,
                api_key=None,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                timeout=1.0,
                sse_dump_dir=str(tmp_path),
            )
        elapsed = time.perf_counter() - started
    finally:
        server.shutdown()
        server.server_close()

    assert elapsed < 1.45
    assert caught.value.kind == "timeout"
    text = (tmp_path / "miniswe-sse-failures").glob("*.sse.txt")
    dumped = [path.read_text(encoding="utf-8") for path in text]
    assert len(dumped) == 1
    assert "token" in dumped[0]
    assert ": ping" in dumped[0]


def test_header_wait_stays_a_socket_timeout(tmp_path: Path) -> None:
    _require_chat_http()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            time.sleep(1.5)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(_data_frame("[DONE]"))
            except OSError:
                return

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server, base = _serve(Handler)
    started = time.perf_counter()
    try:
        with pytest.raises(TransportStall) as caught:
            post_chat_completions(
                api_base=base,
                api_key=None,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                timeout=0.4,
                sse_dump_dir=str(tmp_path),
            )
        elapsed = time.perf_counter() - started
    finally:
        server.shutdown()
        server.server_close()

    assert elapsed < 1.0
    assert "chat_http_content_idle" not in caught.value.message
    assert "ReadTimeout" in caught.value.message
    assert not list((tmp_path / "miniswe-sse-failures").glob("*.sse.txt"))


def test_reasoning_tool_and_content_tokens_reset_content_idle() -> None:
    _require_chat_http()
    reasoning = _data_frame({"choices": [{"delta": {"reasoning_content": "think"}}]})
    tool = _data_frame(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "bash", "arguments": "ls"},
                            }
                        ]
                    }
                }
            ]
        }
    )
    content = _data_frame({"choices": [{"delta": {"content": "z"}, "finish_reason": "tool_calls"}]})
    usage = _data_frame(
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
    )
    script = [
        (0.8, _PING),
        (0.0, reasoning),
        (0.8, _PING),
        (0.0, tool),
        (0.8, _PING),
        (0.0, content),
        (0.8, _data_frame({"choices": [{"delta": {}}]})),
        (0.0, usage),
        (0.0, _data_frame("[DONE]")),
    ]
    server, base = _serve(_scripted_stream(script))
    try:
        result = post_chat_completions(
            api_base=base,
            api_key=None,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            timeout=1.5,
        )
    finally:
        server.shutdown()
        server.server_close()

    message = result.choices[0].message
    assert message.content == "z"
    assert message.tool_calls is not None
    assert message.tool_calls[0].function.name == "bash"
    assert message.tool_calls[0].function.arguments == "ls"
    dumped = message.model_dump()
    assert dumped.get("reasoning_content") == "think"
