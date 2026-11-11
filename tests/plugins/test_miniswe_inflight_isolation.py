"""One query's recycle must not close another query's chat stream.

Local fake SSE only. No live model API.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# A socket closed by this process surfaces as one of these. A remote gateway
# failure is not required, and a successful body is not a pass for the victim.
_LOCAL_CLOSE = (
    "Bad file descriptor",
    "Errno 9",
    "EBADF",
    "ReadError",
    "RemoteProtocolError",
    "TransportStall",
    "incomplete",
    "disconnected",
)


def _sse_chunk(text: str, *, finish: bool = False) -> bytes:
    delta: dict[str, Any] = {"role": "assistant", "content": text} if text else {}
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": "stop" if finish else None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class _Gate:
    def __init__(self) -> None:
        self.n = 0
        self.cv = threading.Condition()

    def arrive(self) -> None:
        with self.cv:
            self.n += 1
            self.cv.notify_all()

    def wait(self, count: int, timeout: float) -> bool:
        with self.cv:
            return bool(self.cv.wait_for(lambda: self.n >= count, timeout))


def _handler(gate: _Gate, words: list[str], delay: float) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            _ = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            gate.arrive()
            try:
                for index, word in enumerate(words):
                    piece = word if index == 0 else f" {word}"
                    self.wfile.write(_sse_chunk(piece, finish=index == len(words) - 1))
                    self.wfile.flush()
                    time.sleep(delay)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                return

    return Handler


def _start(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    return httpd, f"http://{host}:{port}/v1"


def _words() -> list[str]:
    return ["COMPLETE_REPLY_OK", *[f"tok{i}" for i in range(24)]]


def _run_query(api_base: str, started: threading.Event, result: dict[str, Any], key: str) -> None:
    from miniswe_plugin.llm_client import inflight_scope, post_chat_completions

    try:
        with inflight_scope() as scope:
            result[f"{key}_scope"] = scope
            started.set()
            completion = post_chat_completions(
                api_base=api_base,
                api_key="local-test",
                model="dummy",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30,
                extra_body={"max_tokens": 16},
                stream=True,
            )
            text = completion.choices[0].message.content or ""
            result[key] = {"ok": True, "text": text, "error": None, "scope": scope}
    except Exception as exc:  # noqa: BLE001 — the assertion checks this outcome
        result[key] = {
            "ok": False,
            "text": None,
            "error": f"{type(exc).__name__}:{exc}",
            "scope": result.get(f"{key}_scope"),
        }


def _both_streams(base: str) -> tuple[dict[str, Any], threading.Thread, threading.Thread]:
    started_a = threading.Event()
    started_b = threading.Event()
    result: dict[str, Any] = {}
    thread_a = threading.Thread(target=_run_query, args=(base, started_a, result, "a"), daemon=True)
    thread_b = threading.Thread(target=_run_query, args=(base, started_b, result, "b"), daemon=True)
    thread_a.start()
    thread_b.start()
    assert started_a.wait(5) and started_b.wait(5)
    return result, thread_a, thread_b


def test_recycle_one_stream_leaves_the_other() -> None:
    pytest.importorskip("httpx")
    pytest.importorskip("openai")
    from miniswe_plugin.llm_client import recycle_llm_clients

    gate = _Gate()
    httpd, base = _start(_handler(gate, _words(), 0.2))
    try:
        result, thread_a, thread_b = _both_streams(base)
        assert gate.wait(2, 8)
        time.sleep(0.4)
        recycle_llm_clients(scope=result["a_scope"])
        thread_a.join(timeout=20)
        thread_b.join(timeout=20)
        assert not thread_a.is_alive() and not thread_b.is_alive()
        victim, peer = result["a"], result["b"]
        assert peer["ok"] is True, peer
        assert "COMPLETE_REPLY_OK" in (peer["text"] or "")
        assert "tok23" in (peer["text"] or "")
        assert victim["ok"] is False, victim
        error = str(victim["error"])
        assert any(needle in error for needle in _LOCAL_CLOSE), error
        assert victim["scope"] != peer["scope"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_recycle_without_scope_leaves_concurrent_streams() -> None:
    pytest.importorskip("httpx")
    pytest.importorskip("openai")
    from miniswe_plugin.llm_client import recycle_llm_clients

    gate = _Gate()
    httpd, base = _start(_handler(gate, _words(), 0.2))
    try:
        result, thread_a, thread_b = _both_streams(base)
        assert gate.wait(2, 8)
        time.sleep(0.4)

        def _blind_recycle() -> None:
            # This thread has no inflight scope. It must not close either stream.
            recycle_llm_clients()

        threading.Thread(target=_blind_recycle, daemon=True).start()
        thread_a.join(timeout=20)
        thread_b.join(timeout=20)
        assert not thread_a.is_alive() and not thread_b.is_alive()
        for key in ("a", "b"):
            outcome = result[key]
            assert outcome["ok"] is True, outcome
            assert "COMPLETE_REPLY_OK" in (outcome["text"] or "")
            assert "tok23" in (outcome["text"] or "")
    finally:
        httpd.shutdown()
        httpd.server_close()
