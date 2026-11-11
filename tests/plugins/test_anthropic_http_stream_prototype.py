"""Messages SSE protocol tests; fixtures are not live-provider acceptance."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from ageval.config.errors import ConfigError
from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.model.usage import UsageUnavailable
from ageval.plugins.contrib.anthropic_http.executor import AnthropicHTTPExecutor
from ageval.plugins.contrib.anthropic_http.messages_stream import (
    MessagesAssembler,
    SSEDecoder,
    StreamProtocolError,
)
from ageval.plugins.contrib.anthropic_http.options import AnthropicHTTPOptions


def event(kind, **kw):
    return json.dumps({"type": kind, **kw}, ensure_ascii=False)


def text_events():
    return [
        event(
            "message_start",
            message={
                "id": "msg_test",
                "role": "assistant",
                "type": "message",
                "model": "test",
                "content": [],
                "usage": {"input_tokens": 9, "output_tokens": 1},
            },
        ),
        event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
        event("content_block_delta", index=0, delta={"type": "text_delta", "text": "STREAM_"}),
        event("content_block_delta", index=0, delta={"type": "text_delta", "text": "OK"}),
        event("content_block_stop", index=0),
        event(
            "message_delta",
            delta={"stop_reason": "end_turn", "stop_sequence": None},
            usage={"output_tokens": 4},
        ),
        event("message_stop"),
    ]


def consume(frames):
    a = MessagesAssembler()
    for f in frames:
        a.consume(f, at="2026-11-11T03:00:00Z")
    return a


def test_text_and_cumulative_usage():
    a = consume(text_events())
    r = a.result()
    assert r["content"] == [{"type": "text", "text": "STREAM_OK"}]
    assert r.get("usage") == {"input_tokens": 9, "output_tokens": 4}
    assert "".join(e["text"] for e in a.events) == "STREAM_OK"


def test_thinking_signature_and_redacted_blocks():
    frames = text_events()
    extra = [
        event(
            "content_block_start",
            index=1,
            content_block={"type": "thinking", "thinking": "", "signature": ""},
        ),
        event(
            "content_block_delta", index=1, delta={"type": "thinking_delta", "thinking": "thinking"}
        ),
        event(
            "content_block_delta",
            index=1,
            delta={"type": "signature_delta", "signature": "opaque-signature"},
        ),
        event("content_block_stop", index=1),
        event(
            "content_block_start",
            index=2,
            content_block={"type": "redacted_thinking", "data": "opaque-redacted"},
        ),
        event("content_block_stop", index=2),
    ]
    a = consume(frames[:1] + extra + frames[1:])
    r = a.result()
    assert r["content"][1].get("signature") == "opaque-signature"
    assert r["content"][2].get("data") == "opaque-redacted"
    assert "opaque" not in "".join(e["text"] for e in a.events)


def test_tool_fragment_assembly_and_stop():
    frames = text_events()[:1] + [
        event(
            "content_block_start",
            index=0,
            content_block={"type": "tool_use", "id": "call_1", "name": "lookup", "input": {}},
        ),
        event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": '{"q":'},
        ),
        event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": '"ok"}'},
        ),
        event("content_block_stop", index=0),
        event("message_delta", delta={"stop_reason": "tool_use"}),
        event("message_stop"),
    ]
    assert consume(frames).result()["content"][0].get("input") == {"q": "ok"}


def test_fragmented_utf8_crlf():
    frames = text_events()
    frames[2] = event("content_block_delta", index=0, delta={"type": "text_delta", "text": "中文"})
    raw = "".join("event: message\r\ndata: " + f + "\r\n\r\n" for f in frames).encode()
    dec = SSEDecoder()
    out = []
    for value in raw:
        out.extend(dec.feed(bytes([value])))
    out.extend(dec.feed(b"", final=True))
    assert consume(out).result()["content"][0].get("text") == "中文OK"


@pytest.mark.parametrize(
    "frames",
    [
        text_events()[:-1],
        text_events()[:3] + [event("message_stop")],
        text_events()[:-2]
        + [event("message_delta", delta={"stop_reason": "max_tokens"}), event("message_stop")],
    ],
)
def test_incomplete_rejected(frames):
    with pytest.raises(StreamProtocolError):
        consume(frames).result()


@pytest.mark.parametrize("value", ["true", 1, None, {}, []])
def test_stream_bool_strict(value):
    with pytest.raises(ConfigError):
        AnthropicHTTPOptions.parse({"stream": value})


@pytest.mark.parametrize("value", [0, -1, True, "20", float("nan"), float("inf")])
def test_timeout_strict(value):
    with pytest.raises(ConfigError):
        AnthropicHTTPOptions.parse({"stream_idle_timeout_seconds": value})


@pytest.mark.parametrize("bad", ["{", "[]", event("error", error={"message": "do not leak this"})])
def test_bad_frames_rejected(bad):
    with pytest.raises(StreamProtocolError):
        consume([bad])


def test_live_progress_activity_final_and_repeated_call(tmp_path):
    sent = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert d["stream"] is True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            fs = text_events()
            for frame in fs[:3]:
                self.wfile.write(("data: " + frame + "\n\n").encode())
            self.wfile.flush()
            sent.set()
            release.wait(2)
            for frame in fs[3:]:
                self.wfile.write(("data: " + frame + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test", "timeout": 3, "watchdog": 3},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="session1", invoke_request_id="invoke1")
    ex.bind_activity(scope)
    result = {}
    t = threading.Thread(
        target=lambda: result.setdefault("r", ex.invoke("hi", timeout=3, collect_dir=str(tmp_path)))
    )
    try:
        t.start()
        assert sent.wait(1)
        end = time.monotonic() + 1
        while time.monotonic() < end:
            if any(r.payload.get("partial_text") == "STREAM_" for r in log.records):
                break
            time.sleep(0.01)
        else:
            pytest.fail("activity did not advance during request")
        assert t.is_alive()
        release.set()
        t.join(2)
        assert not t.is_alive()
        r = result["r"]
        assert r.ok and r.text == "STREAM_OK"
        assert r.metadata["reader_stopped"]
        assert r.metadata["stream_outcome"] == "ok"
        assert (
            r.metadata["headers_ms"]
            <= r.metadata["first_event_ms"]
            <= r.metadata["first_output_ms"]
            <= r.metadata["last_output_ms"]
        )
        assert (
            len(
                [
                    row
                    for row in log.records
                    if row.kind == "model_turn" and row.status == "completed"
                ]
            )
            == 1
        )
        assert scope.project_messages()[-1]["content"] == "STREAM_OK"
        assert r.usage.completion_tokens == 4
        ex.prepare_invoke()
        second = ex.invoke("again", timeout=3, collect_dir=str(tmp_path))
        assert second.ok
        journal = [
            json.loads(x) for x in (tmp_path / "stream-progress.jsonl").read_text().splitlines()
        ]
        assert len({x["exchange_id"] for x in journal}) == 2
    finally:
        release.set()
        t.join(2)
        ex.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("mode", ["first", "idle", "total", "cancel"])
def test_deadlines_cancel_and_partial_evidence(tmp_path, mode):
    sent = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                if mode != "first":
                    for value in text_events()[:3]:
                        self.wfile.write(("data: " + value + "\n\n").encode())
                    self.wfile.flush()
                sent.set()
                for _ in range(100):
                    time.sleep(0.01)
                    self.wfile.write(("data: " + event("ping") + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    opts: dict[str, Any] = {"stream": True}
    if mode == "first":
        opts["stream_first_event_timeout_seconds"] = 0.12
    if mode == "idle":
        opts["stream_idle_timeout_seconds"] = 0.12
    ex = AnthropicHTTPExecutor(
        model={"id": "test", "timeout": 2, "watchdog": 2},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options=opts,
    )
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="s", invoke_request_id="i")
    ex.bind_activity(scope)
    result = {}
    t = threading.Thread(
        target=lambda: result.setdefault(
            "r", ex.invoke("hi", timeout=0.12 if mode == "total" else 2, collect_dir=str(tmp_path))
        )
    )
    try:
        t.start()
        assert sent.wait(1)
        if mode == "cancel":
            ex.cancel_invoke()
        t.join(2)
        assert not t.is_alive()
        r = result["r"]
        assert not r.ok and not r.text
        assert r.metadata["reader_stopped"]
        assert (
            len([r for r in log.records if r.kind == "model_turn" and r.status == "aborted"]) == 1
        )
        assert not any(r.kind == "model_turn" and r.status == "completed" for r in log.records)
        assert scope.project_messages() == []
    finally:
        ex.close()
        t.join(2)
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("omit", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_explicit_temperature_omission(omit, stream):
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            captured.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.end_headers()
            if stream:
                for value in text_events():
                    self.wfile.write(("data: " + value + "\n\n").encode())
            else:
                self.wfile.write(b'{"content":[{"type":"text","text":"ok"}]}')
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test"},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": stream, "omit_temperature": omit},
    )
    try:
        assert ex.invoke("hi", timeout=3).ok
        assert ("temperature" not in captured) == omit
        if not omit:
            assert captured["temperature"] == 0
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_cancel_before_headers_closes_reader(tmp_path):
    received = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.set()
            release.wait(3)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test", "timeout": 10, "watchdog": 10},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    result = {}
    worker = threading.Thread(
        target=lambda: result.setdefault(
            "r", ex.invoke("hi", timeout=10, collect_dir=str(tmp_path))
        )
    )
    try:
        worker.start()
        assert received.wait(1)
        ex.cancel_invoke()
        worker.join(2)
        assert not worker.is_alive()
        assert result["r"].error == "invoke_cancelled"
        assert result["r"].metadata["reader_stopped"] is True
    finally:
        release.set()
        worker.join(2)
        server.shutdown()
        server.server_close()


def test_provider_error_retains_redacted_details_and_partial_usage(tmp_path):
    secret = "credential-sentinel-328"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for value in text_events()[:3] + [
                event(
                    "error",
                    error={"type": "overloaded_error", "message": "provider rejected " + secret},
                )
            ]:
                self.wfile.write(("data: " + value + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test"},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    try:
        result = ex.invoke(
            "hi", timeout=3, collect_dir=str(tmp_path), redaction_sentinels=(secret,)
        )
        assert not result.ok
        assert result.metadata is not None
        assert result.metadata["stream_error"]["type"] == "overloaded_error"
        assert secret not in json.dumps(result.metadata)
        assert "REDACTED" in result.metadata["stream_error"]["message"]
        assert isinstance(result.usage, UsageUnavailable)
        assert result.usage.reason == "partial"
        assert result.usage.prompt_tokens == 9
        assert secret not in (tmp_path / "stream-progress.jsonl").read_text()
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_options_default_to_non_streaming_and_explicit_temperature():
    opts = AnthropicHTTPOptions.parse({})
    assert opts.stream is False
    assert opts.omit_temperature is False
    assert opts.stream_first_event_timeout_seconds is None
    assert opts.stream_idle_timeout_seconds is None
    with pytest.raises(ConfigError):
        AnthropicHTTPOptions.parse({"omit_temperature": 1})


def test_sse_comments_and_multiline_data():
    raw = b': keepalive\r\nevent: message\r\ndata: {"type":\r\ndata:  "ping"}\r\n\r\n'
    frames = SSEDecoder().feed(raw)
    assert len(frames) == 1
    assert json.loads(frames[0]) == {"type": "ping"}
    assembler = MessagesAssembler()
    counts = assembler.consume(frames[0], at="2026-11-11T03:00:00Z")
    assert counts["assistant_chars"] == 0
    assert SSEDecoder().feed(b": comment only\n\n") == []


def test_interleaved_block_indices_and_ping():
    frames = [
        event(
            "message_start",
            message={
                "id": "msg_interleaved",
                "role": "assistant",
                "type": "message",
                "model": "test",
                "content": [],
                "usage": {"input_tokens": 3},
            },
        ),
        event("ping"),
        event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
        event(
            "content_block_start",
            index=1,
            content_block={"type": "tool_use", "id": "call_1", "name": "lookup", "input": {}},
        ),
        event("ping"),
        event(
            "content_block_delta",
            index=1,
            delta={"type": "input_json_delta", "partial_json": '{"q":'},
        ),
        event("content_block_delta", index=0, delta={"type": "text_delta", "text": "ok"}),
        event(
            "content_block_delta",
            index=1,
            delta={"type": "input_json_delta", "partial_json": '"v"}'},
        ),
        event("content_block_stop", index=0),
        event("content_block_stop", index=1),
        event("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 3}),
        event("message_stop"),
    ]
    assembler = consume(frames)
    result = assembler.result()
    assert [block.get("type") for block in result["content"]] == ["text", "tool_use"]
    assert result["content"][0].get("text") == "ok"
    assert result["content"][1].get("input") == {"q": "v"}
    assert [event["channel"] for event in assembler.events] == ["assistant"]


def test_max_tokens_preserves_partial_events_and_usage(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            frames = [
                text_events()[0],
                event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
                event(
                    "content_block_delta", index=0, delta={"type": "text_delta", "text": "partial"}
                ),
                event("content_block_stop", index=0),
                event(
                    "message_delta",
                    delta={"stop_reason": "max_tokens"},
                    usage={"output_tokens": 5},
                ),
                event("message_stop"),
            ]
            for value in frames:
                self.wfile.write(("data: " + value + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test"},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    try:
        result = ex.invoke("hi", timeout=3, collect_dir=str(tmp_path))
        assert not result.ok
        assert result.error == "ProtocolError:stream_incomplete:max_tokens"
        assert result.metadata is not None
        assert result.metadata["stop_reason"] == "max_tokens"
        assert result.metadata["stream_outcome"] == "protocol"
        assert any(event.get("text") == "partial" for event in result.events)
        assert isinstance(result.usage, UsageUnavailable)
        assert result.usage.reason == "partial"
        assert result.usage.prompt_tokens == 9
        assert result.usage.completion_tokens == 5
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_thinking_only_is_not_an_answer(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            frames = [
                text_events()[0],
                event(
                    "content_block_start",
                    index=0,
                    content_block={"type": "thinking", "thinking": "", "signature": ""},
                ),
                event(
                    "content_block_delta",
                    index=0,
                    delta={"type": "thinking_delta", "thinking": "only thought"},
                ),
                event("content_block_stop", index=0),
                event("message_delta", delta={"stop_reason": "end_turn"}),
                event("message_stop"),
            ]
            for value in frames:
                self.wfile.write(("data: " + value + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test"},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    try:
        result = ex.invoke("hi", timeout=3, collect_dir=str(tmp_path))
        assert not result.ok
        assert not result.text
        assert result.error == "ProtocolError:stream_empty_answer"
        assert any(event.get("channel") == "thought" for event in result.events)
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_http_error_body_is_bounded_and_redacted(tmp_path):
    secret = "credential-sentinel-http-328"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"error": "provider rejected " + secret}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test"},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    try:
        result = ex.invoke(
            "hi", timeout=3, collect_dir=str(tmp_path), redaction_sentinels=(secret,)
        )
        assert not result.ok
        assert result.error == "ModelConfigError:HTTPError:400"
        assert result.metadata is not None
        assert result.metadata["stream_outcome"] == "http"
        assert "REDACTED" in result.metadata["http_error_body"]
        assert secret not in json.dumps(result.metadata)
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_stream_watchdog_keeps_existing_timeout_error(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(80):
                    time.sleep(0.01)
                    self.wfile.write(("data: " + event("ping") + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test", "timeout": 2, "watchdog": 0.15},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True},
    )
    try:
        result = ex.invoke("hi", timeout=2, collect_dir=str(tmp_path))
        assert not result.ok
        assert result.metadata is not None
        assert result.metadata["stream_outcome"] == "watchdog"
        assert str(result.error or "").startswith("TimeoutError:anthropic_http_watchdog:")
    finally:
        ex.close()
        server.shutdown()
        server.server_close()


def test_idle_timeout_starts_at_headers_not_connect(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(0.2)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for value in text_events():
                self.wfile.write(("data: " + value + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ex = AnthropicHTTPExecutor(
        model={"id": "test", "timeout": 3, "watchdog": 3},
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        options={"stream": True, "stream_idle_timeout_seconds": 0.15},
    )
    try:
        result = ex.invoke("hi", timeout=3, collect_dir=str(tmp_path))
        assert result.ok
        assert result.text == "STREAM_OK"
        assert result.metadata is not None
        assert result.metadata["stream_outcome"] == "ok"
        assert result.metadata["headers_ms"] >= 150
    finally:
        ex.close()
        server.shutdown()
        server.server_close()
