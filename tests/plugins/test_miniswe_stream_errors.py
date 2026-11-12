"""miniswe chat SSE: upstream error frames never become an empty reply.

An HTTP 200 stream that carries ``data: {"error": ...}`` (or only a
usage chunk) and then ``[DONE]`` used to assemble into an empty assistant
message. mini-swe-agent then raised ``FormatError`` ("No tool calls found")
and the attempt sealed as a capability FAIL. These cases must raise a
transport failure the parent stall can retry. Offline loopback only.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

pytest.importorskip("httpx")
pytest.importorskip("openai")

from miniswe_plugin.llm_client import post_chat_completions  # noqa: E402
from miniswe_plugin.stall import wrap_model_query  # noqa: E402

from ageval.model.errors import ModelConfigError, ProtocolError, TransportStall  # noqa: E402
from ageval.runtime.upstream_stall import UpstreamStall  # noqa: E402

_SECRET = "sk-test-loopback-secret-0123456789abcdef"

ROLE = {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
TOOL = {
    "id": "chatcmpl-1",
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
                        "function": {"name": "bash", "arguments": '{"command":"ls"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
}
USAGE_ONLY = {
    "choices": [],
    "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
}
GATEWAY_ERROR = {
    "error": {
        "code": "gateway_concurrency_limit",
        "message": f"too many concurrent requests for key {_SECRET}",
    }
}


def _data(obj: Any) -> str:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n"


def _serve(bodies: list[tuple[int, str, str]]) -> tuple[ThreadingHTTPServer, str, list[int]]:
    """Answer each POST with the next (status, content-type, body); repeat the last."""
    hits: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            index = min(len(hits), len(bodies) - 1)
            hits.append(index)
            status, ctype, body = bodies[index]
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1", hits


def _sse(*frames: str) -> tuple[int, str, str]:
    return 200, "text/event-stream", "".join(frames)


def _post(base: str, **kwargs: Any) -> Any:
    return post_chat_completions(
        api_base=base,
        api_key=_SECRET,
        model="openai/m",
        messages=[{"role": "user", "content": "hi"}],
        timeout=5.0,
        stream=kwargs.pop("stream", True),
        **kwargs,
    )


def _run(body: tuple[int, str, str], **kwargs: Any) -> Any:
    server, base, _hits = _serve([body])
    try:
        return _post(base, **kwargs)
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    "frames",
    [
        pytest.param((_data(GATEWAY_ERROR), _data("[DONE]")), id="error-only-then-done"),
        pytest.param(
            ("event: error\n" + _data(GATEWAY_ERROR), _data("[DONE]")),
            id="event-error",
        ),
        pytest.param(
            (
                "event: error\n"
                + _data({"type": "error", "error": {"type": "overloaded_error", "message": "x"}}),
                _data("[DONE]"),
            ),
            id="anthropic-shaped-error",
        ),
        pytest.param((_data(ROLE), _data(GATEWAY_ERROR), _data("[DONE]")), id="role-then-error"),
        pytest.param((_data(TOOL), _data(GATEWAY_ERROR), _data("[DONE]")), id="tools-then-error"),
        pytest.param((_data(GATEWAY_ERROR),), id="error-without-done"),
    ],
)
def test_error_frame_raises_transport_stall(frames: tuple[str, ...]) -> None:
    with pytest.raises(TransportStall) as caught:
        _run(_sse(*frames))
    assert caught.value.kind == "upstream_stream_error"
    assert caught.value.message.startswith("chat_http_stream_error:")
    assert _SECRET not in caught.value.message


def test_error_frame_keeps_code_and_redacts_message() -> None:
    with pytest.raises(TransportStall) as caught:
        _run(_sse(_data(GATEWAY_ERROR), _data("[DONE]")))
    detail = json.loads(caught.value.message.split(":", 1)[1])
    assert detail["code"] == "gateway_concurrency_limit"
    assert "too many concurrent requests" in detail["message"]
    assert _SECRET not in detail["message"]


def test_error_frame_with_non_retryable_status_is_config_error() -> None:
    frame = {"error": {"message": "insufficient balance", "type": "billing_error", "code": 403}}
    with pytest.raises(ModelConfigError, match="chat_http_stream_error"):
        _run(_sse(_data(frame), _data("[DONE]")))


def test_error_frame_with_429_status_stalls() -> None:
    frame = {"error": {"message": "slow down", "status_code": 429}}
    with pytest.raises(TransportStall, match="chat_http_stream_error"):
        _run(_sse(_data(frame), _data("[DONE]")))


def test_usage_only_stream_raises_no_choices() -> None:
    with pytest.raises(TransportStall, match="chat_http_stream_no_choices") as caught:
        _run(_sse(_data(USAGE_ONLY), _data("[DONE]")))
    assert caught.value.kind == "upstream_stream_error"


def test_null_error_field_is_not_an_error() -> None:
    chunk = dict(TOOL, error=None)
    completion = _run(_sse(_data(chunk), _data("[DONE]")))
    assert completion.choices[0].message.tool_calls[0].function.name == "bash"


def test_tool_stream_with_trailing_usage_chunk_still_assembles() -> None:
    content = {"choices": [{"index": 0, "delta": {"content": "looking"}, "finish_reason": None}]}
    completion = _run(
        _sse(_data(ROLE), _data(content), _data(TOOL), _data(USAGE_ONLY), _data("[DONE]"))
    )
    message = completion.choices[0].message
    assert message.content == "looking"
    assert message.tool_calls[0].id == "call_1"
    assert json.loads(message.tool_calls[0].function.arguments) == {"command": "ls"}
    assert completion.choices[0].finish_reason == "tool_calls"
    assert completion.usage is not None and completion.usage.total_tokens == 5


def test_missing_done_is_still_incomplete() -> None:
    with pytest.raises(TransportStall, match="chat_http_stream_incomplete"):
        _run(_sse(_data(TOOL)))


def test_done_only_is_still_protocol_error() -> None:
    with pytest.raises(ProtocolError, match="chat_http_stream_empty"):
        _run(_sse(_data("[DONE]")))


def test_http_429_is_unchanged() -> None:
    body = json.dumps({"error": {"message": "rate limited"}})
    with pytest.raises(TransportStall, match="chat_http_429"):
        _run((429, "application/json", body))


def test_non_stream_200_error_body_is_classified() -> None:
    body = json.dumps(GATEWAY_ERROR)
    with pytest.raises(TransportStall, match="chat_http_body_error"):
        _run((200, "application/json", body), stream=False)


def test_failure_dump_is_bounded_and_redacted(tmp_path: Path) -> None:
    with pytest.raises(TransportStall):
        _run(_sse(_data(ROLE), _data(GATEWAY_ERROR), _data("[DONE]")), sse_dump_dir=str(tmp_path))
    dumps = sorted((tmp_path / "miniswe-sse-failures").glob("*.sse.txt"))
    assert len(dumps) == 1
    assert dumps[0].name.endswith("-stream_error.sse.txt")
    text = dumps[0].read_text(encoding="utf-8")
    assert "gateway_concurrency_limit" in text
    assert '"role": "assistant"' in text
    assert _SECRET not in text


def test_success_writes_no_dump(tmp_path: Path) -> None:
    _run(_sse(_data(TOOL), _data("[DONE]")), sse_dump_dir=str(tmp_path))
    assert not (tmp_path / "miniswe-sse-failures").exists()


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _stall() -> tuple[UpstreamStall, _Clock]:
    clock = _Clock()
    stall = UpstreamStall(
        budget_seconds=3600,
        phase="run",
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        on_event=lambda _event: None,
        on_freeze=lambda: None,
        on_thaw=lambda: None,
        on_fact=lambda _name, _detail: None,
    )
    return stall, clock


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(_sse(_data(GATEWAY_ERROR), _data("[DONE]")), id="error-chunk"),
        pytest.param(_sse(_data(USAGE_ONLY), _data("[DONE]")), id="usage-only"),
    ],
)
def test_stall_wrapper_retries_and_parser_sees_the_good_turn(bad: tuple[int, str, str]) -> None:
    """Through the stall wrapper and mini-swe-agent's parser, end to end."""
    toolcall = pytest.importorskip("minisweagent.models.utils.actions_toolcall")
    server, base, hits = _serve([bad, _sse(_data(TOOL), _data("[DONE]"))])
    stall, clock = _stall()

    def query(messages: Any, **_kwargs: Any) -> Any:
        return _post(base)

    parse: Callable[..., Any] = toolcall.parse_toolcall_actions
    try:
        completion = wrap_model_query(query, stall, watchdog=10.0)([{"role": "user"}])
    finally:
        server.shutdown()
    assert hits == [0, 1]
    assert clock.sleeps == [60.0]
    actions = parse(completion.choices[0].message.tool_calls, format_error_template="{{error}}")
    assert actions[0]["command"] == "ls"
