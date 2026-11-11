"""Messages SSE transport: provider blocks, final usage, and live activity."""

from __future__ import annotations

import codecs
import contextlib
import copy
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast

from ageval.evidence.activity import ActivityScope
from ageval.evidence.redaction import redact_text
from ageval.plugins.contrib.anthropic_http.options import AnthropicHTTPOptions

MAX_BUFFER = 8 * 1024 * 1024

StreamKind = Literal["ok", "http", "protocol", "transport", "cancelled", "watchdog"]


class StreamCounts(TypedDict):
    assistant_chars: int
    thought_chars: int
    tool_chars: int


class TextEvent(TypedDict):
    kind: Literal["text"]
    channel: Literal["assistant", "thought"]
    text: str
    source: str
    at: str


class ContentBlock(TypedDict, total=False):
    """One provider content block. Unknown opaque keys are preserved verbatim."""

    type: str
    text: str
    thinking: str
    signature: str
    data: str
    id: str
    name: str
    input: dict[str, object]


class MessageIdentity(TypedDict, total=False):
    id: str
    model: str
    role: str
    type: str


class MessagesResponse(MessageIdentity):
    content: list[ContentBlock]
    stop_reason: str
    stop_sequence: str | None
    usage: NotRequired[dict[str, object]]


class StreamMeta(TypedDict, total=False):
    stream: bool
    sse_events: int
    assistant_chars: int
    thought_chars: int
    tool_chars: int
    max_idle_ms: float
    headers_ms: float
    first_event_ms: float
    first_output_ms: float
    last_output_ms: float
    duration_ms: float
    reader_stopped: bool
    stream_outcome: StreamKind
    stop_reason: str | None
    stream_error: dict[str, str]


@dataclass(frozen=True, slots=True)
class StreamOutcome:
    """Terminal transport state. ``raw`` is set only for a complete stream."""

    kind: StreamKind
    raw: MessagesResponse | None = None
    message: str | None = None
    http_code: int | None = None
    http_body: str | None = None


@dataclass(slots=True)
class _TransportState:
    connection: http.client.HTTPConnection | None = None
    sock: socket.socket | None = None
    http_code: int | None = None
    http_body: str | None = None
    protocol: str | None = None
    transport: str | None = None
    raw: MessagesResponse | None = None


class StreamExecutor(Protocol):
    """Executor surface the transport needs. Kept local to this plugin."""

    watchdog: float
    http_timeout: float
    options: AnthropicHTTPOptions
    _activity_step: int | None
    _invoke_cancel: threading.Event
    _stream_abort: Callable[[], None] | None
    _stream_events: list[TextEvent]
    _stream_meta: StreamMeta
    _stream_partial_usage: dict[str, object]


class StreamProtocolError(ValueError):
    """An invalid/incomplete stream is not a completed model invocation."""


class StreamProviderError(StreamProtocolError):
    """An in-stream ``error`` event, carrying only bounded provider fields."""

    def __init__(self, details: dict[str, str]) -> None:
        super().__init__("stream_provider_error")
        self.details: dict[str, str] = details


def _json_object(value: object) -> dict[str, object] | None:
    """Validated JSON object boundary. Non-objects are rejected by the caller."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


class SSEDecoder:
    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.pending = ""
        self.data: list[str] = []
        self.size = 0

    def feed(self, chunk: bytes, *, final: bool = False) -> list[str]:
        self.pending += self.decoder.decode(chunk, final=final)
        if len(self.pending) > MAX_BUFFER:
            raise StreamProtocolError("stream_frame_too_large")
        frames: list[str] = []
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            line = line.removesuffix("\r")
            if line == "":
                if self.data:
                    frames.append("\n".join(self.data))
                self.data.clear()
                self.size = 0
            elif line.startswith("data:"):
                value = line[5:]
                if value.startswith(" "):
                    value = value[1:]
                self.data.append(value)
                self.size += len(value)
                if self.size > MAX_BUFFER:
                    raise StreamProtocolError("stream_frame_too_large")
        if final and (self.pending or self.data):
            raise StreamProtocolError("stream_unterminated_frame")
        return frames


class MessagesAssembler:
    def __init__(self) -> None:
        self.started = False
        self.done = False
        self.identity: MessageIdentity = {}
        self.blocks: dict[int, ContentBlock] = {}
        self.open_blocks: set[int] = set()
        self.fragments: dict[int, str] = {}
        self.usage: dict[str, object] = {}
        self.events: list[TextEvent] = []
        self.stop_reason: str | None = None
        self.stop_sequence: str | None = None
        self.characters = 0

    def _emit(
        self,
        text: str,
        channel: Literal["assistant", "thought"],
        at: str,
        progress: StreamCounts,
    ) -> None:
        if not text:
            return
        self.characters += len(text)
        if channel == "assistant":
            progress["assistant_chars"] += len(text)
        else:
            progress["thought_chars"] += len(text)
        event: TextEvent = {
            "kind": "text",
            "channel": channel,
            "text": text,
            "source": "anthropic-http",
            "at": at,
        }
        self.events.append(event)

    def consume(self, frame: str, *, at: str) -> StreamCounts:
        progress: StreamCounts = {"assistant_chars": 0, "thought_chars": 0, "tool_chars": 0}
        try:
            decoded = json.loads(frame)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError("stream_bad_json") from exc
        event = _json_object(decoded)
        if event is None:
            raise StreamProtocolError("stream_event_invalid")
        kind = event.get("type")
        if not isinstance(kind, str):
            raise StreamProtocolError("stream_event_invalid")
        if kind == "error":
            raw = _json_object(event.get("error")) or {}
            details = {
                key: str(raw[key])[:1000] for key in ("type", "code", "message") if key in raw
            }
            raise StreamProviderError(details)
        if kind == "ping":
            return progress
        if self.done:
            raise StreamProtocolError("stream_event_after_stop")
        if kind == "message_start":
            if self.started:
                raise StreamProtocolError("stream_duplicate_message_start")
            message = _json_object(event.get("message"))
            if message is None:
                raise StreamProtocolError("stream_message_start_invalid")
            if message.get("content") not in ([], None):
                raise StreamProtocolError("stream_initial_content_unsupported")
            self.started = True
            message_id = message.get("id")
            if isinstance(message_id, str):
                self.identity["id"] = message_id
            message_model = message.get("model")
            if isinstance(message_model, str):
                self.identity["model"] = message_model
            message_role = message.get("role")
            if isinstance(message_role, str):
                self.identity["role"] = message_role
            message_type = message.get("type")
            if isinstance(message_type, str):
                self.identity["type"] = message_type
            usage = _json_object(message.get("usage"))
            if usage is not None:
                self.usage.update(usage)
            return progress
        if not self.started:
            raise StreamProtocolError("stream_missing_message_start")
        if kind == "message_delta":
            delta = _json_object(event.get("delta"))
            if delta is None:
                raise StreamProtocolError("stream_message_delta_invalid")
            stop_reason = delta.get("stop_reason")
            if isinstance(stop_reason, str):
                self.stop_reason = stop_reason
            elif stop_reason is not None:
                raise StreamProtocolError("stream_message_delta_invalid")
            if "stop_sequence" in delta:
                stop_sequence = delta["stop_sequence"]
                if stop_sequence is not None and not isinstance(stop_sequence, str):
                    raise StreamProtocolError("stream_message_delta_invalid")
                self.stop_sequence = stop_sequence
            usage = _json_object(event.get("usage"))
            if usage is not None:
                # Message delta output_tokens is cumulative, not additive.
                self.usage.update(usage)
            return progress
        if kind == "message_stop":
            if self.open_blocks:
                raise StreamProtocolError("stream_unclosed_blocks")
            self.done = True
            return progress
        index = event.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise StreamProtocolError("stream_block_index_invalid")
        if kind == "content_block_start":
            if index in self.blocks:
                raise StreamProtocolError("stream_duplicate_block")
            raw_block = _json_object(event.get("content_block"))
            if raw_block is None:
                raise StreamProtocolError("stream_block_type_unsupported")
            block_type = raw_block.get("type")
            if not isinstance(block_type, str) or block_type not in {
                "text",
                "thinking",
                "redacted_thinking",
                "tool_use",
            }:
                raise StreamProtocolError("stream_block_type_unsupported")
            if len(self.blocks) >= 1024:
                raise StreamProtocolError("stream_block_count_exceeded")
            self.characters += len(json.dumps(raw_block, ensure_ascii=False))
            if self.characters > MAX_BUFFER:
                raise StreamProtocolError("stream_output_too_large")
            if block_type in {"text", "thinking"}:
                field = "text" if block_type == "text" else "thinking"
                initial = raw_block.get(field, "")
                if not isinstance(initial, str):
                    raise StreamProtocolError("stream_initial_text_invalid")
            block = cast(ContentBlock, copy.deepcopy(raw_block))
            self.blocks[index] = block
            self.open_blocks.add(index)
            if block_type == "text":
                initial_text = block.get("text")
                if isinstance(initial_text, str):
                    self._emit(initial_text, "assistant", at, progress)
            if block_type == "thinking":
                initial_thought = block.get("thinking")
                if isinstance(initial_thought, str):
                    self._emit(initial_thought, "thought", at, progress)
            return progress
        if index not in self.open_blocks:
            raise StreamProtocolError("stream_block_not_open")
        block = self.blocks[index]
        if kind == "content_block_stop":
            if block.get("type") == "tool_use":
                block_id = block.get("id")
                block_name = block.get("name")
                if (
                    not isinstance(block_id, str)
                    or not block_id
                    or not isinstance(block_name, str)
                    or not block_name
                ):
                    raise StreamProtocolError("stream_tool_identity_missing")
                if index in self.fragments:
                    try:
                        value = json.loads(self.fragments[index])
                    except json.JSONDecodeError as exc:
                        raise StreamProtocolError("stream_tool_json_incomplete") from exc
                    if not isinstance(value, dict):
                        raise StreamProtocolError("stream_tool_input_not_object")
                    block["input"] = cast(dict[str, object], value)
                else:
                    initial_input = block.get("input")
                    if initial_input is not None and not isinstance(initial_input, dict):
                        raise StreamProtocolError("stream_tool_input_not_object")
            self.open_blocks.remove(index)
            return progress
        if kind != "content_block_delta":
            raise StreamProtocolError("stream_event_type_unsupported")
        delta = _json_object(event.get("delta"))
        if delta is None:
            raise StreamProtocolError("stream_block_delta_invalid")
        dtype = delta.get("type")
        if dtype == "text_delta" and block.get("type") == "text":
            part = delta.get("text")
            if not isinstance(part, str):
                raise StreamProtocolError("stream_text_delta_invalid")
            block["text"] = str(block.get("text") or "") + part
            self._emit(part, "assistant", at, progress)
        elif dtype == "thinking_delta" and block.get("type") == "thinking":
            part = delta.get("thinking")
            if not isinstance(part, str):
                raise StreamProtocolError("stream_thinking_delta_invalid")
            block["thinking"] = str(block.get("thinking") or "") + part
            self._emit(part, "thought", at, progress)
        elif dtype == "signature_delta" and block.get("type") == "thinking":
            part = delta.get("signature")
            if not isinstance(part, str):
                raise StreamProtocolError("stream_signature_delta_invalid")
            block["signature"] = str(block.get("signature") or "") + part
            self.characters += len(part)
        elif dtype == "input_json_delta" and block.get("type") == "tool_use":
            part = delta.get("partial_json")
            if not isinstance(part, str):
                raise StreamProtocolError("stream_tool_delta_invalid")
            self.fragments[index] = self.fragments.get(index, "") + part
            progress["tool_chars"] += len(part)
            self.characters += len(part)
        else:
            raise StreamProtocolError("stream_delta_type_mismatch")
        if self.characters > MAX_BUFFER or len(self.events) > 100000:
            raise StreamProtocolError("stream_output_too_large")
        return progress

    def result(self) -> MessagesResponse:
        if not self.done:
            raise StreamProtocolError("stream_missing_message_stop")
        stop_reason = self.stop_reason
        if not isinstance(stop_reason, str) or stop_reason not in {
            "end_turn",
            "stop_sequence",
            "tool_use",
        }:
            raise StreamProtocolError("stream_incomplete:" + str(stop_reason))
        blocks = [self.blocks[i] for i in sorted(self.blocks)]
        if not any(
            (block.get("type") == "text" and str(block.get("text") or "").strip())
            or block.get("type") == "tool_use"
            for block in blocks
        ):
            raise StreamProtocolError("stream_empty_answer")
        has_tools = any(block.get("type") == "tool_use" for block in blocks)
        if (stop_reason == "tool_use") != has_tools:
            raise StreamProtocolError("stream_tool_stop_mismatch")
        raw = cast(
            MessagesResponse,
            {
                **self.identity,
                "content": blocks,
                "stop_reason": stop_reason,
                "stop_sequence": self.stop_sequence,
            },
        )
        if self.usage:
            raw["usage"] = self.usage
        return raw


def exchange_messages_stream(
    executor: StreamExecutor,
    req: urllib.request.Request,
    *,
    timeout: float,
    collect_dir: str | None,
    redaction_sentinels: tuple[str, ...] | list[str] | None = None,
) -> StreamOutcome:
    start = time.monotonic()
    join_for = executor.watchdog
    watchdog_ceiling = True
    try:
        invoke_cap = float(timeout)
    except (TypeError, ValueError):
        invoke_cap = executor.watchdog
    if invoke_cap > 0 and invoke_cap < executor.watchdog:
        join_for = invoke_cap
        watchdog_ceiling = False
    deadline = start + join_for
    lock = threading.RLock()
    stop = threading.Event()
    box = _TransportState()
    assembler = MessagesAssembler()
    decoder = SSEDecoder()
    meta: StreamMeta = {
        "stream": True,
        "sse_events": 0,
        "assistant_chars": 0,
        "thought_chars": 0,
        "tool_chars": 0,
        "max_idle_ms": 0.0,
    }
    last_progress = start
    idle_since = start
    last_activity_write = 0.0
    sentinels = tuple(redaction_sentinels or ())
    exchange_id = uuid.uuid4().hex
    journal = None
    if collect_dir:
        p = Path(collect_dir) / "stream-progress.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        journal = p.open("a", encoding="utf-8")

    def record(event: str, **fields: Any) -> None:
        if journal:
            journal.write(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "exchange_id": exchange_id,
                        "event": event,
                        "elapsed_ms": round((time.monotonic() - start) * 1000, 3),
                        **fields,
                    }
                )
                + "\n"
            )
            journal.flush()

    def activity_progress() -> None:
        nonlocal last_activity_write
        stamp = time.monotonic()
        if stamp - last_activity_write < 0.25:
            return
        last_activity_write = stamp
        scope = getattr(executor, "activity", None)
        if not isinstance(scope, ActivityScope):
            return
        step = executor._activity_step
        if not isinstance(step, int):
            return
        identity = f"mt_{scope.invoke_request_id}_{step}"
        old = next(
            (
                row
                for row in reversed(scope.log.records)
                if row.request_id == identity and row.status == "in_flight"
            ),
            None,
        )
        if old is None:
            return
        payload = dict(old.payload)
        payload["partial_text"] = "".join(
            event["text"] for event in assembler.events if event["channel"] == "assistant"
        )
        payload["partial_thought"] = "".join(
            event["text"] for event in assembler.events if event["channel"] == "thought"
        )
        payload["stream_event_count"] = meta["sse_events"]
        scope.log.append(
            request_id=identity, kind="model_turn", status="in_flight", payload=payload
        )

    def abort() -> None:
        stop.set()
        with lock:
            connection = box.connection
            sock = box.sock
            if sock is None and connection is not None:
                candidate = getattr(connection, "sock", None)
                if isinstance(candidate, socket.socket):
                    sock = candidate
        if isinstance(sock, socket.socket):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    executor._stream_abort = abort

    def reader() -> None:
        nonlocal last_progress, idle_since
        try:

            class TrackedHTTPConnection(http.client.HTTPConnection):
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    super().__init__(*args, **kwargs)
                    with lock:
                        box.connection = self

                def connect(self) -> None:
                    super().connect()
                    if stop.is_set():
                        self.close()
                        raise OSError("stream_cancelled_before_headers")  # noqa: TRY301 - connection abort boundary

            class TrackedHTTPSConnection(http.client.HTTPSConnection):
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    super().__init__(*args, **kwargs)
                    with lock:
                        box.connection = self

                def connect(self) -> None:
                    super().connect()
                    if stop.is_set():
                        self.close()
                        raise OSError("stream_cancelled_before_headers")  # noqa: TRY301 - connection abort boundary

            class HTTPHandler(urllib.request.HTTPHandler):
                def http_open(self, req: urllib.request.Request) -> Any:
                    return self.do_open(TrackedHTTPConnection, req)

            class HTTPSHandler(urllib.request.HTTPSHandler):
                def https_open(self, req: urllib.request.Request) -> Any:
                    return self.do_open(
                        TrackedHTTPSConnection, req, context=getattr(self, "_context", None)
                    )

            opener = urllib.request.build_opener(HTTPHandler(), HTTPSHandler())
            with opener.open(req, timeout=min(executor.http_timeout, join_for)) as response:
                with lock:
                    raw_socket = getattr(response.fp.raw, "_sock", None)
                    box.sock = raw_socket if isinstance(raw_socket, socket.socket) else None
                    if stop.is_set():
                        return
                    meta["headers_ms"] = round((time.monotonic() - start) * 1000, 3)
                    idle_since = time.monotonic()
                    record("headers", http_status=response.status)
                if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
                    raise StreamProtocolError("stream_content_type_invalid")  # noqa: TRY301
                while not stop.is_set():
                    chunk = response.read1(4096)
                    if not chunk:
                        decoder.feed(b"", final=True)
                        break
                    for frame in decoder.feed(chunk):
                        with lock:
                            if stop.is_set():
                                return
                            now = time.monotonic()
                            meta.setdefault("first_event_ms", round((now - start) * 1000, 3))
                            meta["sse_events"] += 1
                            counts = assembler.consume(frame, at=datetime.now(UTC).isoformat())
                            if any(counts.values()):
                                meta.setdefault("first_output_ms", round((now - start) * 1000, 3))
                                meta["max_idle_ms"] = max(
                                    meta["max_idle_ms"], round((now - last_progress) * 1000, 3)
                                )
                                last_progress = now
                                idle_since = now
                                meta["last_output_ms"] = round((now - start) * 1000, 3)
                                activity_progress()
                            for key, value in counts.items():
                                meta[key] += value
                            record("sse", **counts, done=assembler.done)
                            if assembler.done:
                                meta["stop_reason"] = assembler.stop_reason
                                box.raw = assembler.result()
                                return
                if not stop.is_set():
                    raise StreamProtocolError("stream_premature_eof")  # noqa: TRY301
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(4096).decode("utf-8", errors="replace")
            except (OSError, http.client.HTTPException):
                body = "stream HTTP rejection (body unavailable)"
            with lock:
                box.http_code = exc.code
                box.http_body = redact_text(body, extra_sentinels=sentinels)
            exc.close()
        except StreamProviderError as exc:
            with lock:
                box.protocol = "stream_provider_error"
                meta["stream_error"] = {
                    key: redact_text(value, extra_sentinels=sentinels)
                    for key, value in exc.details.items()
                }
        except (StreamProtocolError, UnicodeDecodeError) as exc:
            with lock:
                box.protocol = (
                    str(exc) if isinstance(exc, StreamProtocolError) else "stream_utf8_invalid"
                )
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            with lock:
                box.transport = type(exc).__name__

    record("stream_started")
    worker = threading.Thread(target=reader, name="anthropic-messages-sse", daemon=True)
    worker.start()
    outcome = StreamOutcome("transport", message="stream_unknown_failure")
    try:
        while worker.is_alive():
            now = time.monotonic()
            with lock:
                first = meta.get("first_event_ms")
                idle = now - idle_since
            if executor._invoke_cancel.is_set():
                outcome = StreamOutcome("cancelled")
                abort()
                break
            if now >= deadline:
                outcome = (
                    StreamOutcome("watchdog")
                    if watchdog_ceiling
                    else StreamOutcome("transport", message="stream_total_timeout")
                )
                abort()
                break
            if (
                first is None
                and executor.options.stream_first_event_timeout_seconds
                and now - start >= executor.options.stream_first_event_timeout_seconds
            ):
                outcome = StreamOutcome("transport", message="stream_first_event_timeout")
                abort()
                break
            if (
                first is not None
                and executor.options.stream_idle_timeout_seconds
                and idle >= executor.options.stream_idle_timeout_seconds
            ):
                outcome = StreamOutcome("transport", message="stream_idle_timeout")
                abort()
                break
            worker.join(0.02)
        else:
            with lock:
                if box.http_code is not None:
                    outcome = StreamOutcome(
                        "http", http_code=box.http_code, http_body=box.http_body
                    )
                elif box.protocol is not None:
                    outcome = StreamOutcome("protocol", message=box.protocol)
                elif box.transport is not None:
                    outcome = StreamOutcome("transport", message=box.transport)
                elif box.raw is not None:
                    outcome = StreamOutcome("ok", raw=box.raw)
        if executor._invoke_cancel.is_set():
            outcome = StreamOutcome("cancelled")
            abort()
        if worker.is_alive():
            worker.join(1)
        with lock:
            stop.set()
            meta["duration_ms"] = round((time.monotonic() - start) * 1000, 3)
            meta["reader_stopped"] = not worker.is_alive()
            meta["stream_outcome"] = outcome.kind
            executor._stream_events = list(assembler.events)
            executor._stream_meta = meta
            executor._stream_partial_usage = dict(assembler.usage)
            record(
                "stream_finished",
                outcome=outcome.kind,
                reader_stopped=meta["reader_stopped"],
            )
        return outcome
    finally:
        stop.set()
        executor._stream_abort = None
        with lock:
            if journal:
                journal.close()
