"""Drop empty OpenAI tool-call id/name on SSE so DSH official adapter can merge.

``@deepseek-ai/dsh-llm-deepseek`` (through rc.8) does::

    if (call.id !== undefined) block.callId = call.id
    if (call.function?.name !== undefined) block.name = call.function.name

Official DeepSeek omits those fields on argument-only deltas. Some OpenAI
gateways (LiteLLM → DashScope) send ``id: ""`` / ``name: ""``, which are
defined and wipe the first-chunk ``bash`` / call id. The harness then
dispatches ``unknown tool ""``.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "host",
        "accept-encoding",
    }
)


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def strip_empty_tool_call_fields(obj: Any) -> bool:
    """Omit empty ``id`` / ``function.name`` on OpenAI ``delta.tool_calls``.

    Mutates ``obj``. Returns True when anything was removed.
    """
    if not isinstance(obj, dict):
        return False
    changed = False
    for choice in obj.get("choices") or ():
        if not isinstance(choice, dict):
            continue
        for delta_key in ("delta", "message"):
            blob = choice.get(delta_key)
            if not isinstance(blob, dict):
                continue
            calls = blob.get("tool_calls")
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                if "id" in call and _is_blank(call.get("id")):
                    del call["id"]
                    changed = True
                fn = call.get("function")
                if isinstance(fn, dict) and "name" in fn and _is_blank(fn.get("name")):
                    del fn["name"]
                    changed = True
    return changed


def rewrite_sse_line(line: str) -> str:
    """Rewrite one SSE line (no trailing LF). Preserves a trailing CR."""
    cr = line.endswith("\r")
    raw = line[:-1] if cr else line
    suffix = "\r" if cr else ""
    if not raw.startswith("data:"):
        return raw + suffix
    payload = raw[5:].lstrip()
    if payload == "[DONE]" or not payload:
        return raw + suffix
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return raw + suffix
    if not strip_empty_tool_call_fields(obj):
        return raw + suffix
    return "data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + suffix


def rewrite_sse_buffer(buf: str) -> str:
    """Rewrite complete SSE lines in a decoded chunk; keep a trailing partial line."""
    if not buf:
        return buf
    ends_nl = buf.endswith("\n")
    parts = buf.split("\n")
    if not ends_nl:
        tail = parts[-1]
        parts = parts[:-1]
    else:
        tail = ""
    out = [rewrite_sse_line(p) for p in parts]
    text = "\n".join(out)
    if ends_nl:
        text += "\n"
    if tail:
        text += tail
    return text


class SanitizingProxy:
    """Loopback reverse proxy that rewrites empty tool-call fields on SSE."""

    def __init__(self, upstream: str) -> None:
        parsed = urlparse(upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"dsh_sanitize_upstream_invalid:{upstream!r}")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._path_prefix = parsed.path.rstrip("/")
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        origin = self._origin

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                del format, args

            def do_GET(self) -> None:  # noqa: N802
                self._forward()

            def do_POST(self) -> None:  # noqa: N802
                self._forward()

            def do_PUT(self) -> None:  # noqa: N802
                self._forward()

            def do_DELETE(self) -> None:  # noqa: N802
                self._forward()

            def _forward(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length > 0 else None
                url = origin + self.path
                headers: dict[str, str] = {}
                for key, val in self.headers.items():
                    if key.lower() in _HOP:
                        continue
                    headers[key] = val
                headers["Accept-Encoding"] = "identity"
                req = Request(url, data=body, headers=headers, method=self.command)
                try:
                    resp = urlopen(req, timeout=None)  # noqa: S310 — operator-chosen upstream
                except HTTPError as err:
                    resp = err
                except (URLError, TimeoutError, HTTPException, OSError) as exc:
                    self.send_error(502, f"dsh_sanitize_upstream:{type(exc).__name__}")
                    return
                try:
                    status = int(getattr(resp, "status", None) or getattr(resp, "code", 502))
                    self.send_response(status)
                    ctype = ""
                    src_headers = getattr(resp, "headers", None)
                    if src_headers is not None:
                        for key, val in src_headers.items():
                            if key.lower() in _HOP:
                                continue
                            if key.lower() == "content-type":
                                ctype = val
                            self.send_header(key, val)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    stream = "text/event-stream" in ctype.lower()
                    leftover = b""
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        if not stream:
                            self.wfile.write(chunk)
                            continue
                        leftover += chunk
                        nls = leftover.rfind(b"\n")
                        if nls < 0:
                            continue
                        complete, leftover = leftover[: nls + 1], leftover[nls + 1 :]
                        text = rewrite_sse_buffer(complete.decode("utf-8", errors="replace"))
                        self.wfile.write(text.encode("utf-8"))
                        self.wfile.flush()
                    if leftover:
                        if stream:
                            text = rewrite_sse_buffer(leftover.decode("utf-8", errors="replace"))
                            self.wfile.write(text.encode("utf-8"))
                        else:
                            self.wfile.write(leftover)
                finally:
                    with contextlib.suppress(OSError):
                        resp.close()

        self._handler = Handler

    def start(self) -> None:
        if self._httpd is not None:
            return
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler)
        self._httpd = httpd
        thread = threading.Thread(target=httpd.serve_forever, name="dsh-sse-sanitize", daemon=True)
        self._thread = thread
        thread.start()

    @property
    def local_base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("dsh_sanitize_proxy_not_started")
        port = int(self._httpd.server_address[1])
        return f"http://127.0.0.1:{port}{self._path_prefix}"

    def close(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)


def start_sanitizing_proxy(upstream: str) -> SanitizingProxy:
    proxy = SanitizingProxy(upstream)
    proxy.start()
    return proxy


@contextmanager
def sanitizing_base_url(
    env: MutableMapping[str, str] | None = None,
) -> Iterator[str | None]:
    """If ``DEEPSEEK_BASE_URL`` is set, proxy it and rewrite the env value."""
    mapping: MutableMapping[str, str]
    mapping = env if env is not None else _os_environ()
    upstream = (mapping.get("DEEPSEEK_BASE_URL") or "").strip()
    if not upstream:
        yield None
        return
    proxy = start_sanitizing_proxy(upstream)
    mapping["DEEPSEEK_BASE_URL"] = proxy.local_base_url
    try:
        yield proxy.local_base_url
    finally:
        mapping["DEEPSEEK_BASE_URL"] = upstream
        proxy.close()


def _os_environ() -> MutableMapping[str, str]:
    import os

    return os.environ
