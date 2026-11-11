"""Incremental HTTP/SSE transport shared by first-party API executors.

Provider payload assembly belongs to the executor (for example
``openai_http.stream``). This module owns only the reusable wire mechanics:

* one incremental UTF-8 decoder and SSE frame assembler (CRLF, comments,
  multi-line ``data:`` fields, split/coalesced frames, bounded buffers);
* one reader thread that consumes frames as they arrive and records monotonic
  header/first-event/first-output timing;
* cancellation and deadline handling that closes the local response/socket;
* a consumer protocol so a provider module folds frames into its own shape.

The consumer contract is deliberately small::

    class Consumer(Protocol):
        done: bool
        def feed(self, frame: str, *, at: str) -> dict[str, int]: ...
        def finish(self) -> Any: ...
        def snapshot(self) -> StreamSnapshot: ...

``feed`` returns integer progress counters (for example
``{"assistant_chars": 12}``); transport sums them without interpreting text.
Raising ``StreamProtocolError`` ends the exchange as ``protocol`` and keeps the
partial ``snapshot()``. ``finish`` is called once after the consumer's terminal
or at EOF, and returns the provider-shaped response document. Provider modules
must never fall back to another API shape.

Reuse rule: an executor-specific assembler lives next to that executor. Only
framing, timing, cancellation, and socket cleanup live here.
"""

from __future__ import annotations

import codecs
import contextlib
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

MAX_BUFFER = 8 * 1024 * 1024
MAX_EVENTS = 100_000
POLL_SECONDS = 0.02
READ_SIZE = 4096
JOIN_GRACE_SECONDS = 1.0

EventHook = Callable[[str, Mapping[str, Any]], None]


def utc_at() -> str:
    """UTC timestamp with millisecond precision and a ``Z`` suffix."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class StreamProtocolError(ValueError):
    """A stream cannot be interpreted as one complete model turn.

    ``details`` carries provider-reported error type/code/message when the
    failure is upstream rather than a local parse error. Callers redact it
    before sealing.
    """

    def __init__(
        self,
        kind: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.details = dict(details) if details else None


@dataclass(frozen=True, slots=True)
class StreamSnapshot:
    """Best-effort partial turn for an error result or an aborted model turn."""

    text: str = ""
    thought: str = ""
    tool_calls: tuple[dict[str, object], ...] = ()
    usage: dict[str, object] | None = None
    stop_reason: str | None = None
    status: str | None = None
    events: tuple[dict[str, object], ...] = ()
    error_details: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class StreamOutcome:
    """One exchange result. ``detail`` is provider-shaped only for ``ok``."""

    kind: str
    detail: Any = None
    metrics: dict[str, object] = field(default_factory=dict)
    snapshot: StreamSnapshot = field(default_factory=StreamSnapshot)


class StreamConsumer(Protocol):
    """Provider-specific frame folder consumed by :func:`exchange_sse`."""

    done: bool

    def feed(self, frame: str, *, at: str) -> dict[str, int]: ...

    def finish(self) -> Any: ...

    def snapshot(self) -> StreamSnapshot: ...


class DeltaSink(Protocol):
    """Live per-fragment sink (activity log, progress journal, or a no-op)."""

    def append(
        self,
        channel: str,
        text: str,
        *,
        tool_index: int | None = None,
        tool_call_id: str | None = None,
    ) -> None: ...


class StreamProgressJournal:
    """Append-only timing/count journal under a raw-collection directory.

    Never writes fragments, headers, or credential material. Each line carries
    the exchange id so repeated invokes sharing one directory stay separable.
    """

    def __init__(self, collect_dir: str | None) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._handle: Any = None
        self.exchange_id = uuid4().hex
        if collect_dir:
            self._path = Path(collect_dir) / "stream-progress.jsonl"
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")

    def __call__(self, event: str, fields: Mapping[str, Any]) -> None:
        if self._handle is None:
            return
        row = {
            "at": utc_at(),
            "exchange_id": self.exchange_id,
            "event": event,
            **dict(fields),
        }
        with self._lock:
            self._handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None


__all__ = [
    "DeltaSink",
    "MAX_BUFFER",
    "MAX_EVENTS",
    "SSEDecoder",
    "StreamConsumer",
    "StreamOutcome",
    "StreamProgressJournal",
    "StreamProtocolError",
    "StreamSnapshot",
    "exchange_sse",
    "utc_at",
]


class SSEDecoder:
    """Incremental UTF-8/SSE framing with bounded buffers.

    Comments (``:`` lines), ``event:``, ``id:`` and ``retry:`` fields are
    framing, not answer progress. Empty ``data:`` lines are ignored until a
    frame terminator yields them.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._pending = ""
        self._data: list[str] = []
        self._frame_size = 0
        self.comments = 0
        self.frames = 0

    def feed(self, chunk: bytes, *, final: bool = False) -> list[str]:
        text = self._decoder.decode(chunk, final=final)
        self._pending += text
        if len(self._pending) > MAX_BUFFER:
            raise StreamProtocolError("stream_frame_too_large")
        frames: list[str] = []
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._line(line, frames)
        if final:
            if self._pending:
                line, self._pending = self._pending, ""
                self._line(line, frames)
            if self._data:
                frames.append("\n".join(self._data))
                self._data.clear()
                self._frame_size = 0
        return frames

    def _line(self, line: str, frames: list[str]) -> None:
        line = line.removesuffix("\r")
        if line == "":
            if self._data:
                frames.append("\n".join(self._data))
                self.frames += 1
            self._data.clear()
            self._frame_size = 0
            return
        if line.startswith(":"):
            self.comments += 1
            return
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            self._frame_size += len(value)
            if self._frame_size > MAX_BUFFER:
                raise StreamProtocolError("stream_frame_too_large")
            self._data.append(value)


def exchange_sse(
    req: urllib.request.Request,
    *,
    consumer: StreamConsumer,
    http_timeout: float,
    total_timeout: float,
    watchdog_ceiling: bool,
    cancel: threading.Event,
    first_event_timeout: float | None,
    idle_timeout: float | None,
    on_event: EventHook | None = None,
) -> StreamOutcome:
    """POST ``req`` and consume SSE frames until terminal, deadline, or cancel.

    ``total_timeout`` is the fixed ceiling for the whole exchange. It is
    computed by the executor (the shorter of the invoke timeout and the
    watchdog) and never extended by arriving chunks. ``first_event_timeout``
    counts from request start to the first SSE data frame. ``idle_timeout``
    counts from the last meaningful fragment (text/thought/tool characters);
    comments and heartbeat frames do not reset it.

    On every exit path the local response and its socket are closed. A reader
    that is still blocked when the exchange returns is marked
    ``reader_stopped: false`` rather than hidden.
    """

    start = time.monotonic()
    deadline = start + total_timeout
    abort = _Abort()
    box = _Box()
    metrics = _Metrics(start)
    decoder = SSEDecoder()

    def record(event: str, **fields: Any) -> None:
        if on_event is not None:
            on_event(event, {"exchange_started_ms": 0.0, **fields})

    def consume(frames: list[str]) -> None:
        for frame in frames:
            if abort.stop.is_set():
                return
            at = utc_at()
            counts = consumer.feed(frame, at=at)
            now = time.monotonic()
            snapshot = metrics.frame(now, counts, comments=decoder.comments, frames=decoder.frames)
            record("sse", **snapshot, done=consumer.done)
            if consumer.done:
                box.set_raw(consumer.finish())
                return

    def reader() -> None:
        try:
            opener = _tracking_opener(abort)
            resp = opener.open(req, timeout=http_timeout)
            with resp:
                status = _status_of(resp)
                _attach_response(abort, resp)
                if abort.stop.is_set():
                    return
                headers_ms = metrics.headers()
                record("headers", http_status=status, headers_ms=headers_ms)
                if status != 200:
                    box.set_http(status, _read_status_body(resp))
                    return
                _require_event_stream(resp)
                while not abort.stop.is_set():
                    chunk = resp.read1(READ_SIZE)
                    if not chunk:
                        break
                    frames = decoder.feed(chunk)
                    metrics.comments(decoder.comments)
                    consume(frames)
                    if box.has_raw():
                        return
                if abort.stop.is_set():
                    return
                frames = decoder.feed(b"", final=True)
                metrics.comments(decoder.comments)
                consume(frames)
                if box.has_raw():
                    return
                box.set_raw(consumer.finish())
        except urllib.error.HTTPError as exc:
            body = _http_error_body(exc)
            box.set_http(exc.code, body)
            exc.close()
        except StreamProtocolError as exc:
            box.set_protocol(exc.kind)
        except UnicodeDecodeError:
            box.set_protocol("stream_utf8_invalid")
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            box.set_transport(type(exc).__name__)

    worker = threading.Thread(target=reader, name="ageval-http-sse", daemon=True)
    worker.start()
    kind: str | None = None
    detail: Any = None
    try:
        while worker.is_alive():
            now = time.monotonic()
            if cancel.is_set():
                kind, detail = "cancelled", None
                break
            if now >= deadline:
                kind = "watchdog" if watchdog_ceiling else "transport"
                detail = None if watchdog_ceiling else "TimeoutError"
                break
            if (
                first_event_timeout is not None
                and metrics.first_event_ms() is None
                and now - start >= first_event_timeout
            ):
                kind, detail = "transport", "stream_first_event_timeout"
                break
            if idle_timeout is not None and now - metrics.last_output_at() >= idle_timeout:
                kind, detail = "transport", "stream_idle_timeout"
                break
            worker.join(POLL_SECONDS)
        if kind is not None:
            abort.abort()
        if worker.is_alive():
            worker.join(JOIN_GRACE_SECONDS)
        if cancel.is_set():
            # The parent cancelled this invocation. The local reader may have
            # observed the shutdown as a transport error; cancellation wins.
            kind, detail = "cancelled", None
        elif kind is None:
            kind, detail = box.outcome()
        metrics.set_outcome(kind)
        final_metrics = metrics.snapshot(reader_stopped=not worker.is_alive())
        record("finished", **final_metrics)
        return StreamOutcome(
            kind=kind,
            detail=detail,
            metrics=final_metrics,
            snapshot=consumer.snapshot(),
        )
    finally:
        abort.stop.set()
        if worker.is_alive():
            abort.abort()
        record("stream_closed", reader_stopped=not worker.is_alive())


class _Box:
    """Reader result, guarded because the main thread only polls the worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_code: int | None = None
        self._http_body = ""
        self._protocol: str | None = None
        self._transport: str | None = None
        self._raw: Any = None
        self._has_raw = False

    def set_http(self, code: int, body: str) -> None:
        with self._lock:
            self._http_code = code
            self._http_body = body

    def set_protocol(self, kind: str) -> None:
        with self._lock:
            self._protocol = kind

    def set_transport(self, kind: str) -> None:
        with self._lock:
            self._transport = kind

    def set_raw(self, raw: Any) -> None:
        with self._lock:
            self._raw = raw
            self._has_raw = True

    def has_raw(self) -> bool:
        with self._lock:
            return self._has_raw

    def outcome(self) -> tuple[str, Any]:
        with self._lock:
            if self._http_code is not None:
                return "http", {"http_code": self._http_code, "http_body": self._http_body}
            if self._protocol is not None:
                return "protocol", self._protocol
            if self._transport is not None:
                return "transport", self._transport
            if self._has_raw:
                return "ok", self._raw
        return "transport", "stream_unknown_failure"


class _Metrics:
    """Monotonic stream timing; counts only, never fragments."""

    def __init__(self, start: float) -> None:
        self._lock = threading.Lock()
        self._start = start
        self._first_event_ms: float | None = None
        self._first_output_ms: float | None = None
        self._last_output_at = start
        self._last_output_ms: float | None = None
        self._max_idle_ms = 0.0
        self._counts: dict[str, int] = {
            "sse_events": 0,
            "heartbeat_events": 0,
            "assistant_chars": 0,
            "thought_chars": 0,
            "tool_chars": 0,
        }
        self._headers_ms: float | None = None
        self._outcome = "unknown"

    def headers(self) -> float:
        with self._lock:
            self._headers_ms = _ms(self._start)
            return self._headers_ms

    def frame(
        self,
        now: float,
        counts: Mapping[str, int],
        *,
        comments: int,
        frames: int,
    ) -> dict[str, object]:
        progress = sum(value for value in counts.values() if value > 0)
        with self._lock:
            if self._first_event_ms is None:
                self._first_event_ms = round((now - self._start) * 1000, 3)
            if progress > 0:
                idle = round((now - self._last_output_at) * 1000, 3)
                self._max_idle_ms = max(self._max_idle_ms, idle)
                if self._first_output_ms is None:
                    self._first_output_ms = round((now - self._start) * 1000, 3)
                self._last_output_at = now
                self._last_output_ms = round((now - self._start) * 1000, 3)
            for key, value in counts.items():
                if isinstance(value, int) and not isinstance(value, bool) and value:
                    self._counts[key] = self._counts.get(key, 0) + value
            self._counts["sse_events"] += 1
            self._counts["heartbeat_events"] = comments
            self._counts["parsed_frames"] = frames
            return {
                **self._counts,
                "first_event_ms": self._first_event_ms,
                "first_output_ms": self._first_output_ms,
                "last_output_ms": self._last_output_ms,
                "max_idle_ms": self._max_idle_ms,
            }

    def comments(self, count: int) -> None:
        with self._lock:
            self._counts["heartbeat_events"] = count

    def first_event_ms(self) -> float | None:
        with self._lock:
            return self._first_event_ms

    def last_output_at(self) -> float:
        with self._lock:
            return self._last_output_at

    def set_outcome(self, outcome: str) -> None:
        with self._lock:
            self._outcome = outcome

    def snapshot(self, *, reader_stopped: bool) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            idle = round((now - self._last_output_at) * 1000, 3)
            self._max_idle_ms = max(self._max_idle_ms, idle)
            return {
                "stream": True,
                **self._counts,
                "headers_ms": self._headers_ms,
                "first_event_ms": self._first_event_ms,
                "first_output_ms": self._first_output_ms,
                "last_output_ms": self._last_output_ms,
                "max_idle_ms": self._max_idle_ms,
                "duration_ms": round((now - self._start) * 1000, 3),
                "reader_stopped": reader_stopped,
                "stream_outcome": _protocol_outcome(self._outcome),
            }


class _Abort:
    """Abort flag plus the local connection/response handles."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.stop = threading.Event()
        self._connection: Any = None
        self._response: Any = None
        self._socket: socket.socket | None = None

    def attach_connection(self, connection: Any) -> None:
        with self._lock:
            self._connection = connection

    def attach_response(self, response: Any) -> None:
        sock = _response_socket(response)
        with self._lock:
            self._response = response
            self._socket = sock

    def abort(self) -> None:
        self.stop.set()
        with self._lock:
            sock = self._socket
            response = self._response
            connection = self._connection
        _close_socket(sock)
        # A response owns its file object; the reader's ``with resp`` closes it
        # once the shutdown unblocks the read. Closing it here would race the
        # reader into ``fp is None`` inside HTTPResponse._close_conn.
        if response is None and connection is not None:
            conn_sock = getattr(connection, "sock", None)
            if isinstance(conn_sock, socket.socket):
                _close_socket(conn_sock)
            with contextlib.suppress(OSError, ValueError):
                connection.close()


def _tracking_opener(abort: _Abort) -> urllib.request.OpenerDirector:
    """An opener whose connections are reachable before response headers."""

    class TrackedHTTPConnection(http.client.HTTPConnection):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            abort.attach_connection(self)

    class TrackedHTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            abort.attach_connection(self)

    class TrackedHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req: urllib.request.Request) -> Any:
            return self.do_open(TrackedHTTPConnection, req)

    class TrackedHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req: urllib.request.Request) -> Any:
            return self.do_open(
                TrackedHTTPSConnection,
                req,
                context=self._context,  # type: ignore[attr-defined]
            )

    return urllib.request.build_opener(TrackedHTTPHandler, TrackedHTTPSHandler)


def _attach_response(abort: _Abort, response: Any) -> None:
    abort.attach_response(response)


def _status_of(response: Any) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        code = getcode()
        if isinstance(code, int):
            return code
    return 0


def _require_event_stream(response: Any) -> None:
    if "text/event-stream" not in _content_type(response).lower():
        raise StreamProtocolError("stream_content_type_invalid")


def _content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    raw = headers.get("Content-Type", "")
    return raw if isinstance(raw, str) else ""


def _read_status_body(response: Any) -> str:
    try:
        raw = response.read(800)
    except (OSError, http.client.HTTPException):
        return ""
    return _decode_body(raw)


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(800)
    except (OSError, http.client.HTTPException):
        return ""
    return _decode_body(raw)


def _decode_body(raw: Any) -> str:
    if not isinstance(raw, bytes):
        return ""
    return raw.decode("utf-8", errors="replace")


def _response_socket(response: Any) -> socket.socket | None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if isinstance(sock, socket.socket):
        return sock
    return None


def _close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        sock.close()


def _ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 3)


def _protocol_outcome(kind: str) -> str:
    return {
        "ok": "completed",
        "protocol": "protocol_error",
        "http": "http_error",
        "transport": "transport_error",
        "cancelled": "cancelled",
        "watchdog": "watchdog",
    }.get(kind, kind)
