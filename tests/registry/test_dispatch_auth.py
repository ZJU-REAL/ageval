"""Dispatch enforces Route.access before any mutating handler body."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from services.registry.app import build_default_state, make_handler


def _start(tmp_path: Path) -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    state, admin = build_default_state(
        tmp_path / "reg", bootstrap_token="admin-tok", memory_blob=True
    )
    state.tokens.add("reader-tok", frozenset({"results:read"}), github_user="reader")
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, {"state": state, "admin": admin, "reader": "reader-tok"}


def test_publish_without_scope_does_not_enter_store(tmp_path: Path) -> None:
    server, ctx = _start(tmp_path)
    port = server.server_address[1]
    calls: list[Any] = []
    packages_store = ctx["state"].stores.packages
    original = packages_store.insert

    def _spy(row: Any) -> None:
        calls.append(row)
        return original(row)

    packages_store.insert = _spy  # type: ignore[method-assign]
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        body = b'--x\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n{}\r\n--x--\r\n'
        conn.request(
            "POST",
            "/v1/packages",
            body=body,
            headers={
                "Authorization": f"Bearer {ctx['reader']}",
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 401
        assert payload["error"] == "unauthorized"
        assert calls == []
    finally:
        server.shutdown()
        server.server_close()
