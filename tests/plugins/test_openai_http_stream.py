"""openai-http native streaming: synthetic SSE parser and executor evidence.

Loopback fixtures verify framing, assembly, clock, cancellation, and activity
contracts. They are not real-provider acceptance; that stays an explicit
opt-in check through the public CLI.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ageval.config.errors import ConfigError
from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.model.errors import ModelConfigError, ProtocolError, TransportStall
from ageval.model.usage import UsageUnavailable
from ageval.plugins.contrib.openai_http.executor import OpenAIHTTPExecutor
from ageval.plugins.contrib.openai_http.options import OpenAIHTTPOptions
from ageval.plugins.executor_capabilities import get_capabilities
from ageval.plugins.http_stream import SSEDecoder, StreamProtocolError


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def _executor(base: str, *, api: str = "chat", **options: Any) -> OpenAIHTTPExecutor:
    return OpenAIHTTPExecutor(
        model={"id": "mock", "api": api, "timeout": 5, "watchdog": 5},
        base_url=base,
        options={"stream": True, **options},
    )


def _chat_frame(
    delta: dict[str, Any] | None = None,
    finish: str | None = None,
    **extra: Any,
) -> str:
    return json.dumps(
        {
            "id": "chat-test",
            "model": "mock",
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
            **extra,
        }
    )


def _responses_event(kind: str, **fields: Any) -> str:
    return json.dumps({"type": kind, **fields})


def _sse(*frames: str) -> bytes:
    return "".join(f"data: {frame}\n\n" for frame in frames).encode("utf-8")


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length)
    loaded = json.loads(raw.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


class _Recorder:
    def __init__(self) -> None:
        self.body: dict[str, Any] = {}
        self.path = ""
        self.authorization: str | None = None
        self.headers: dict[str, str] = {}
        self.response_headers: dict[str, str] = {}


def _stream_success_handler(
    frames: bytes,
    recorder: _Recorder,
    *,
    content_type: str = "text/event-stream",
    response_headers: dict[str, str] | None = None,
) -> type[BaseHTTPRequestHandler]:
    recorder.response_headers = dict(response_headers or {})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            recorder.path = self.path
            recorder.authorization = self.headers.get("Authorization")
            recorder.headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
            recorder.body = _read_body(self)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            for name, value in recorder.response_headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(frames)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def test_sse_decoder_handles_fragmented_utf8_crlf_and_multiline_data() -> None:
    raw = ': ping\r\ndata: {"value":\r\ndata: "中文"}\r\n\r\ndata: [DONE]\r\n\r\n'.encode()
    decoder = SSEDecoder()
    frames: list[str] = []
    for byte in raw:
        frames.extend(decoder.feed(bytes([byte])))
    frames.extend(decoder.feed(b"", final=True))
    assert json.loads(frames[0]) == {"value": "中文"}
    assert frames[-1] == "[DONE]"
    assert decoder.comments == 1


def test_stream_capability_is_native_events() -> None:
    caps = get_capabilities("openai-http")
    assert caps is not None
    assert caps.stream == "native-events"


def test_chat_stream_text_reasoning_usage_and_timing(tmp_path: Path) -> None:
    recorder = _Recorder()
    frames = _sse(
        _chat_frame({"reasoning_content": "think "}),
        _chat_frame({"content": "STREAM_"}),
        _chat_frame({"content": "OK"}, finish="stop"),
        json.dumps({"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3}}),
        "[DONE]",
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    assert recorder.body["stream"] is True
    assert recorder.body["stream_options"] == {"include_usage": True}
    assert recorder.body["model"] == "mock"
    assert result.ok is True
    assert result.error is None
    assert result.text == "STREAM_OK"
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 2
    assert result.usage["completion_tokens"] == 3
    assert [event["channel"] for event in result.events if event["kind"] == "text"] == [
        "thought",
        "assistant",
        "assistant",
    ]
    metadata = result.metadata or {}
    assert metadata["stream"] is True
    assert metadata["stream_outcome"] == "completed"
    assert metadata["answer_complete"] is True
    assert metadata["stop_reason"] == "stop"
    assert metadata["reader_stopped"] is True
    for key in (
        "headers_ms",
        "first_event_ms",
        "first_output_ms",
        "last_output_ms",
        "max_idle_ms",
        "duration_ms",
        "sse_events",
        "assistant_chars",
        "thought_chars",
    ):
        assert key in metadata


def test_chat_stream_tool_only_and_split_arguments() -> None:
    recorder = _Recorder()
    frames = _sse(
        _chat_frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "look", "arguments": '{"q":'},
                    }
                ]
            }
        ),
        _chat_frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {"name": "up", "arguments": '"hi"}'},
                    }
                ]
            },
            finish="tool_calls",
        ),
        "[DONE]",
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == ""
    assert result.tool_calls == ({"id": "call_1", "name": "lookup", "arguments": {"q": "hi"}},)
    assert result.events == (
        {
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "call_1",
            "function_name": "lookup",
            "title": "lookup",
            "args": {"q": "hi"},
            "status": "pending",
            "source": "openai-http",
        },
    )
    metadata = result.metadata or {}
    assert metadata["tool_chars"] > 0


def test_chat_stream_length_limit_preserves_partial_text_but_is_not_ok() -> None:
    recorder = _Recorder()
    frames = _sse(
        _chat_frame({"content": "partial"}),
        _chat_frame(finish="length"),
        "[DONE]",
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.repeatable is False
    assert isinstance(result.failure, ProtocolError)
    assert result.error == "ProtocolError:stream_incomplete:length"
    assert result.text == "partial"
    metadata = result.metadata or {}
    assert metadata["stop_reason"] == "length"
    assert metadata["answer_complete"] is False
    assert metadata["error_origin"] == "provider_incomplete"
    assert metadata["stream_error"]["stop_reason"] == "length"


def test_chat_stream_missing_done_is_premature_eof() -> None:
    recorder = _Recorder()
    frames = _sse(_chat_frame({"content": "partial"}, finish="stop"))
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_missing_done"
    assert result.text == "partial"


def test_chat_stream_error_event_never_leaks_provider_text(tmp_path: Path) -> None:
    recorder = _Recorder()
    frames = _sse(
        _chat_frame({"content": "partial"}),
        json.dumps(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "code": "server_error",
                    "message": "do-not-log-this Authorization: Bearer sk-abcdefgh12345678",
                },
            }
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_upstream_error"
    assert result.text == "partial"
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "upstream"
    details = metadata["stream_error"]
    assert details["type"] == "invalid_request_error"
    assert details["code"] == "server_error"
    assert "do-not-log-this" in details["message"]
    assert "sk-abcdefgh12345678" not in details["message"]
    assert "[REDACTED:secret]" in details["message"]
    journal = (tmp_path / "stream-progress.jsonl").read_text(encoding="utf-8")
    assert "do-not-log-this" not in journal
    assert "partial" not in journal


def test_chat_stream_heartbeats_do_not_satisfy_first_event_timeout() -> None:
    started = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            started.set()
            try:
                for _ in range(100):
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                return

    server, base = _serve(Handler)
    try:
        begin = time.monotonic()
        result = _executor(base, stream_first_event_timeout_seconds=0.12).invoke("hi")
        elapsed = time.monotonic() - begin
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "stream_first_event_timeout"
    assert result.metadata is not None
    assert result.metadata["reader_stopped"] is True
    assert result.metadata["heartbeat_events"] > 0
    assert elapsed < 2.0


def test_chat_stream_idle_timeout_ignores_heartbeats() -> None:
    started = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            started.set()
            try:
                self.wfile.write(_sse(_chat_frame({"content": "partial"})))
                self.wfile.flush()
                for _ in range(100):
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                return

    server, base = _serve(Handler)
    try:
        result = _executor(base, stream_idle_timeout_seconds=0.12).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "stream_idle_timeout"
    assert result.text == "partial"
    assert result.metadata is not None
    assert result.metadata["heartbeat_events"] > 0
    assert result.metadata["max_idle_ms"] >= 100


def test_chat_stream_outer_timeout_does_not_extend_with_progress() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for index in range(200):
                    self.wfile.write(_sse(_chat_frame({"content": f"{index},"})))
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                return

    server, base = _serve(Handler)
    executor = OpenAIHTTPExecutor(
        model={"id": "mock", "timeout": 2, "watchdog": 2},
        base_url=base,
        options={"stream": True},
    )
    try:
        begin = time.monotonic()
        result = executor.invoke("hi", timeout=0.15)
        elapsed = time.monotonic() - begin
    finally:
        executor.close()
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "TimeoutError"
    assert result.metadata is not None
    assert result.metadata["reader_stopped"] is True
    assert elapsed < 2.0


def test_chat_stream_cancel_before_headers_closes_local_socket() -> None:
    started = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            started.set()
            time.sleep(5)

    server, base = _serve(Handler)
    executor = OpenAIHTTPExecutor(
        model={"id": "mock", "timeout": 30, "watchdog": 30},
        base_url=base,
        options={"stream": True},
    )
    box: dict[str, Any] = {}

    def run() -> None:
        box["result"] = executor.invoke("hi", timeout=30)

    worker = Thread(target=run, daemon=True)
    try:
        worker.start()
        assert started.wait(2)
        begin = time.monotonic()
        executor.cancel_invoke()
        worker.join(2)
        elapsed = time.monotonic() - begin
    finally:
        executor.close()
        server.shutdown()
        server.server_close()

    assert worker.is_alive() is False
    result = box["result"]
    assert result.ok is False
    assert result.error == "invoke_cancelled"
    assert result.repeatable is False
    assert result.metadata is not None
    assert result.metadata["reader_stopped"] is True
    assert elapsed < 2.0


@pytest.mark.parametrize(
    ("code", "expected", "repeatable", "failure_type"),
    [
        (401, "ModelConfigError:HTTPError:401", False, ModelConfigError),
        (500, "HTTPError:500", True, TransportStall),
    ],
)
def test_chat_stream_http_status_mapping(
    code: int, expected: str, repeatable: bool, failure_type: type[BaseException]
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            raw = json.dumps({"error": {"message": "nope"}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server, base = _serve(Handler)
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == expected
    assert result.repeatable is repeatable
    assert isinstance(result.failure, failure_type)
    assert (result.metadata or {})["answer_complete"] is False


def test_chat_stream_rejects_non_sse_content_type() -> None:
    recorder = _Recorder()
    raw = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    server, base = _serve(_stream_success_handler(raw, recorder, content_type="application/json"))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_content_type_invalid"


def test_chat_stream_missing_usage_is_not_reported_not_zero() -> None:
    recorder = _Recorder()
    frames = _sse(_chat_frame({"content": "ok"}, finish="stop"), "[DONE]")
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert isinstance(result.usage, UsageUnavailable)
    assert result.usage.reason == "not_reported"
    assert not result.usage


def test_chat_stream_disabled_keeps_one_json_body() -> None:
    recorder = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            recorder.body = _read_body(self)
            raw = json.dumps({"choices": [{"message": {"content": "plain"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server, base = _serve(Handler)
    try:
        result = OpenAIHTTPExecutor(model={"id": "mock"}, base_url=base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == "plain"
    assert "stream" not in recorder.body
    assert "stream_options" not in recorder.body


def _responses_completed(output: list[dict[str, Any]], **extra: Any) -> str:
    response = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "model": "mock",
        "output": output,
        **extra,
    }
    return _responses_event("response.completed", response=response)


def _response_message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def test_responses_stream_text_reasoning_tools_and_usage() -> None:
    recorder = _Recorder()
    output = [
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "think"}]},
        _response_message("STREAM_OK"),
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"q":"hi"}',
        },
    ]
    frames = _sse(
        _responses_event(
            "response.created",
            response={"id": "resp_1", "object": "response", "status": "in_progress", "output": []},
        ),
        _responses_event(
            "response.output_item.added",
            output_index=0,
            item={"type": "reasoning", "id": "rs_1", "summary": []},
        ),
        _responses_event(
            "response.reasoning_summary_text.delta",
            item_id="rs_1",
            output_index=0,
            summary_index=0,
            delta="think",
        ),
        _responses_event(
            "response.output_item.added",
            output_index=1,
            item={"type": "message", "id": "msg_1", "role": "assistant", "content": []},
        ),
        _responses_event(
            "response.output_text.delta",
            item_id="msg_1",
            output_index=1,
            content_index=0,
            delta="STREAM_",
        ),
        _responses_event(
            "response.output_text.delta",
            item_id="msg_1",
            output_index=1,
            content_index=0,
            delta="OK",
        ),
        _responses_event(
            "response.output_item.added",
            output_index=2,
            item={
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "",
            },
        ),
        _responses_event(
            "response.function_call_arguments.delta",
            item_id="fc_1",
            output_index=2,
            delta='{"q":',
        ),
        _responses_event(
            "response.function_call_arguments.delta",
            item_id="fc_1",
            output_index=2,
            delta='"hi"}',
        ),
        _responses_completed(
            output,
            usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert recorder.path.endswith("/responses")
    assert recorder.body["stream"] is True
    assert "stream_options" not in recorder.body
    assert result.ok is True
    assert result.text == "STREAM_OK"
    assert result.tool_calls == ({"id": "call_1", "name": "lookup", "arguments": {"q": "hi"}},)
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 2
    assert result.usage["completion_tokens"] == 3
    assert [event["channel"] for event in result.events if event["kind"] == "text"] == [
        "thought",
        "assistant",
        "assistant",
    ]
    assert (result.metadata or {})["stop_reason"] == "completed"


def test_responses_stream_completed_without_output_uses_assembled_deltas() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.output_item.added",
            output_index=0,
            item={"type": "message", "id": "msg_1", "role": "assistant", "content": []},
        ),
        _responses_event(
            "response.output_text.delta",
            item_id="msg_1",
            output_index=0,
            content_index=0,
            delta="assembled",
        ),
        _responses_event(
            "response.completed",
            response={"id": "resp_1", "object": "response", "status": "completed"},
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == "assembled"


def test_responses_stream_tool_only_output() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.output_item.added",
            output_index=0,
            item={
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "",
            },
        ),
        _responses_event(
            "response.function_call_arguments.delta",
            item_id="fc_1",
            output_index=0,
            delta='{"q":"hi"}',
        ),
        _responses_completed([]),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    assert result.text == ""
    assert result.tool_calls == ({"id": "call_1", "name": "lookup", "arguments": {"q": "hi"}},)


def test_responses_incomplete_is_not_ok_and_preserves_partial_output() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.incomplete",
            response={
                "id": "resp_1",
                "object": "response",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [_response_message("partial")],
                "usage": {"input_tokens": 2, "output_tokens": 1},
            },
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_incomplete:max_output_tokens"
    assert result.text == "partial"
    metadata = result.metadata or {}
    assert metadata["stop_reason"] == "max_output_tokens"
    assert metadata["error_origin"] == "provider_incomplete"
    assert metadata["stream_error"]["reason"] == "max_output_tokens"
    assert result.repeatable is False


def test_responses_failed_is_not_ok() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.failed",
            response={
                "id": "resp_1",
                "object": "response",
                "status": "failed",
                "error": {"code": "server_error", "message": "do-not-log"},
            },
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_upstream_error"
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "upstream"
    assert metadata["stream_error"]["code"] == "server_error"
    assert metadata["stream_error"]["message"] == "do-not-log"


def test_responses_missing_terminal_is_premature() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.output_text.delta",
            item_id="msg_1",
            output_index=0,
            content_index=0,
            delta="partial",
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_missing_terminal"
    assert result.text == "partial"


def test_responses_bare_done_is_not_a_completed_answer() -> None:
    recorder = _Recorder()
    server, base = _serve(_stream_success_handler(_sse("[DONE]"), recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_missing_terminal"


def test_responses_stream_never_falls_back_to_chat_chunks() -> None:
    recorder = _Recorder()
    frames = _sse(_chat_frame({"content": "chat-shaped"}, finish="stop"), "[DONE]")
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_event_type_invalid"


def test_responses_invalid_tool_json_is_not_a_success() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_completed(
            [
                _response_message("text"),
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"q":',
                },
            ]
        )
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_tool_json_incomplete"
    assert result.text == "text"


def test_live_activity_delta_before_completion_and_single_seal(tmp_path: Path) -> None:
    release = threading.Event()
    sent = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                self.wfile.write(_sse(_chat_frame({"content": "first"})))
                self.wfile.flush()
                sent.set()
                release.wait(2)
                self.wfile.write(_sse(_chat_frame({"content": "second"}, finish="stop"), "[DONE]"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    server, base = _serve(Handler)
    log = ActivityLog.open(tmp_path / "activity.jsonl", sentinels=("SECRET_VALUE",))
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
    executor = _executor(base)
    executor.bind_activity(scope)
    box: dict[str, Any] = {}

    def run() -> None:
        box["result"] = executor.invoke("hi")

    worker = Thread(target=run, daemon=True)
    try:
        worker.start()
        assert sent.wait(2)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if any(record.status == "delta" for record in log.records):
                break
            time.sleep(0.01)
        assert any(
            record.status == "delta" and record.payload.get("text") == "first"
            for record in log.records
        )
        assert worker.is_alive()
        release.set()
        worker.join(2)
    finally:
        release.set()
        executor.close()
        worker.join(2)
        server.shutdown()
        server.server_close()

    result = box["result"]
    assert result.ok is True
    assert result.text == "firstsecond"
    deltas = [record for record in log.records if record.kind == "model_turn"]
    assert [record.status for record in deltas].count("completed") == 1
    assert not any(record.status == "aborted" for record in deltas)
    assert (
        "".join(
            str(record.payload.get("text") or "") for record in deltas if record.status == "delta"
        )
        == "firstsecond"
    )


def test_stream_timeout_options_are_validated() -> None:
    for value in (0, -1, True, "20", float("nan"), float("inf")):
        with pytest.raises(ConfigError):
            OpenAIHTTPOptions.parse({"stream_first_event_timeout_seconds": value})
        with pytest.raises(ConfigError):
            OpenAIHTTPOptions.parse({"stream_idle_timeout_seconds": value})


@pytest.mark.parametrize("value", ["true", 1, None, {}, []])
def test_stream_bool_is_strict(value: Any) -> None:
    with pytest.raises(ConfigError):
        OpenAIHTTPOptions.parse({"stream": value})


def test_stream_sse_decoder_bounds_a_frame() -> None:
    decoder = SSEDecoder()
    with pytest.raises(StreamProtocolError):
        decoder.feed(b"data: " + b"x" * (9 * 1024 * 1024))


def test_chat_stream_malformed_frame_is_a_protocol_error() -> None:
    recorder = _Recorder()
    server, base = _serve(
        _stream_success_handler(_sse(_chat_frame({"content": "partial"}), "{"), recorder)
    )
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_bad_json"
    assert result.text == "partial"
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "parse"
    assert "stream_error" not in metadata


def test_chat_stream_tool_calls_finish_without_tools_is_incomplete() -> None:
    recorder = _Recorder()
    frames = _sse(_chat_frame(finish="tool_calls"), "[DONE]")
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_missing_tool_calls"


def test_responses_stream_error_event_is_a_protocol_error() -> None:
    recorder = _Recorder()
    frames = _sse(
        _responses_event(
            "response.output_text.delta",
            item_id="msg_1",
            output_index=0,
            content_index=0,
            delta="partial",
        ),
        _responses_event("error", code="server_error", message="do-not-log"),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base, api="responses").invoke("hi")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_upstream_error"
    assert result.text == "partial"
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "upstream"
    assert metadata["stream_error"]["code"] == "server_error"
    assert metadata["stream_error"]["message"] == "do-not-log"


def test_chat_stream_correlation_headers_and_exchange_id(tmp_path: Path) -> None:
    recorder = _Recorder()
    frames = _sse(_chat_frame({"content": "ok"}, finish="stop"), "[DONE]")
    server, base = _serve(
        _stream_success_handler(
            frames,
            recorder,
            response_headers={
                "x-litellm-call-id": "call_abc123",
                "x-request-id": "req_abc123",
            },
        )
    )
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is True
    correlation = (result.metadata or {})["stream_correlation"]
    assert correlation["exchange_id"] == recorder.headers["x-client-request-id"]
    assert correlation["x_client_request_id"] == correlation["exchange_id"]
    assert correlation["x_litellm_call_id"] == "call_abc123"
    assert correlation["x_request_id"] == "req_abc123"
    journal = [
        json.loads(line) for line in (tmp_path / "stream-progress.jsonl").read_text().splitlines()
    ]
    assert journal
    assert {row["exchange_id"] for row in journal} == {correlation["exchange_id"]}
    text = (tmp_path / "stream-progress.jsonl").read_text(encoding="utf-8")
    assert "call_abc123" not in text
    assert "req_abc123" not in text


def test_chat_stream_provider_error_allowlist_redacts_credentials_and_urls(
    tmp_path: Path,
) -> None:
    recorder = _Recorder()
    frames = _sse(
        _chat_frame({"content": "partial"}),
        json.dumps(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded",
                    "status_code": 413,
                    "request_id": "req_provider_123",
                    "message": (
                        "POST https://gateway.internal/v1/chat?api_key=sk-abcdefgh12345678 "
                        "Authorization: Bearer sk-abcdefgh12345678"
                    ),
                },
            }
        ),
    )
    server, base = _serve(_stream_success_handler(frames, recorder))
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    assert result.error == "ProtocolError:stream_upstream_error"
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "upstream"
    details = metadata["stream_error"]
    assert details["type"] == "invalid_request_error"
    assert details["code"] == "context_length_exceeded"
    assert details["status_code"] == 413
    assert details["request_id"] == "req_provider_123"
    assert "[REDACTED:url]" in details["message"]
    assert "[REDACTED:secret]" in details["message"]
    assert "gateway.internal" not in details["message"]
    assert "sk-abcdefgh12345678" not in details["message"]
    journal = (tmp_path / "stream-progress.jsonl").read_text(encoding="utf-8")
    for leaked in (
        "gateway.internal",
        "sk-abcdefgh12345678",
        "context_length_exceeded",
        "req_provider_123",
        "Authorization",
    ):
        assert leaked not in journal
    assert '"error_origin": "upstream"' in journal


def test_chat_stream_http_rejection_body_uses_the_same_allowlist(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            raw = json.dumps(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                        "status_code": 401,
                        "request_id": "req_http_123",
                        "message": "GET https://gateway.internal/v1/chat?token=sk-secret123",
                    }
                }
            ).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("x-litellm-call-id", "call_http_123")
            self.send_header("x-request-id", "req_header_123")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server, base = _serve(Handler)
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok is False
    metadata = result.metadata or {}
    assert metadata["error_origin"] == "http"
    details = metadata["http_error"]
    assert details["type"] == "invalid_request_error"
    assert details["code"] == "invalid_api_key"
    assert details["status_code"] == 401
    assert details["request_id"] == "req_http_123"
    assert "[REDACTED:url]" in details["message"]
    assert "gateway.internal" not in details["message"]
    assert "sk-secret123" not in details["message"]
    assert "http_error_body" not in metadata
    correlation = metadata["stream_correlation"]
    assert correlation["x_litellm_call_id"] == "call_http_123"
    assert correlation["x_request_id"] == "req_header_123"
    journal = (tmp_path / "stream-progress.jsonl").read_text(encoding="utf-8")
    for leaked in ("gateway.internal", "sk-secret123", "req_http_123", "invalid_api_key"):
        assert leaked not in journal
    assert '"error_origin": "http"' in journal


def test_chat_stream_http_rejection_non_json_body_is_not_copied(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            _read_body(self)
            raw = (
                b"<html>provider body with sk-should-not-appear and https://gateway.internal</html>"
            )
            self.send_response(502)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server, base = _serve(Handler)
    try:
        result = _executor(base).invoke("hi", collect_dir=str(tmp_path))
    finally:
        server.shutdown()
        server.server_close()

    metadata = result.metadata or {}
    assert result.ok is False
    assert metadata["http_error"] == {
        "origin": "http",
        "terminal": "http_rejection",
        "status_code": 502,
    }
    journal = (tmp_path / "stream-progress.jsonl").read_text(encoding="utf-8")
    assert "provider body" not in journal
    assert "gateway.internal" not in journal
