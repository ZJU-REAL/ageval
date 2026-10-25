"""Unix-socket framing and server for ParentAgentService.

Worker/SDK talks length-prefixed JSON over a Unix domain socket.
"""

from __future__ import annotations

import contextlib
import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from ageval.runtime.parent_agent import ParentAgentService


def _recv_msg(conn: socket.socket) -> dict[str, Any]:
    hdr = _read_exact(conn, 4)
    (n,) = struct.unpack("!I", hdr)
    if n > 4_000_000:
        raise ValueError("frame too large")
    body = _read_exact(conn, n)
    return json.loads(body.decode("utf-8"))


def _send_msg(conn: socket.socket, obj: dict[str, Any]) -> None:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    conn.sendall(struct.pack("!I", len(raw)) + raw)


def _read_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError("socket closed")
        buf += chunk
    return buf


class AgentServiceServer:
    """Unix-socket server exposing ParentAgentService to the task worker."""

    def __init__(self, service: ParentAgentService, socket_path: Path) -> None:
        self.service = service
        self.socket_path = socket_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: socket.socket | None = None
        self._handlers: set[threading.Thread] = set()
        self._handler_lock = threading.Lock()

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.socket_path))
        # A box may run as its own uid; the socket sits in a private directory,
        # so the reachable surface is still only this Attempt.
        self.socket_path.chmod(0o666)
        srv.listen(128)
        srv.settimeout(0.5)
        self._server = srv
        self._thread = threading.Thread(target=self._loop, name="ageval-agent-service", daemon=True)
        self._thread.start()

    def seal_run(self) -> None:
        """Close run-phase sessions; leave the socket up for evaluate."""
        self.service.seal_run()

    def stop(self) -> None:
        """Close every session, then the socket. No Agent can write after this."""
        for session_id in self.service.open_session_ids():
            self.service.close_session(session_id=session_id)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for handler in list(self._handlers):
            handler.join(timeout=2.0)
        if self._server is not None:
            with contextlib.suppress(OSError):
                self._server.close()
        if self.socket_path.exists():
            with contextlib.suppress(OSError):
                self.socket_path.unlink()

    def _loop(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            handler = threading.Thread(
                target=self._serve_one,
                args=(conn,),
                name="ageval-agent-request",
                daemon=True,
            )
            with self._handler_lock:
                self._handlers.add(handler)
            handler.start()

    def _serve_one(self, conn: socket.socket) -> None:
        try:
            try:
                with conn:
                    req = _recv_msg(conn)
                    resp = self._handle(req)
                    _send_msg(conn, resp)
            except Exception as exc:  # noqa: BLE001
                with contextlib.suppress(OSError):
                    _send_msg(
                        conn,
                        {
                            "ok": False,
                            "error": type(exc).__name__,
                            "message": str(exc),
                        },
                    )
        finally:
            with self._handler_lock:
                self._handlers.discard(threading.current_thread())

    def _handle(self, req: dict[str, Any]) -> dict[str, Any]:
        op = req.get("op")
        if op == "open":
            # Client-supplied attempt_id is ignored; parent binding is authoritative.
            actor_raw = req.get("actor_id")
            actor_id = (
                str(actor_raw).strip() if isinstance(actor_raw, str) and actor_raw.strip() else None
            )
            environment_raw = req.get("environment")
            environment = (
                str(environment_raw).strip()
                if isinstance(environment_raw, str) and environment_raw.strip()
                else None
            )
            return self.service.open_session(
                profile_id=str(req.get("profile_id") or ""),
                actor_id=actor_id,
                environment=environment,
            )
        if op == "invoke":
            tools = req.get("tools")
            messages = req.get("messages")
            request_id = req.get("request_id")
            turn_index = req.get("turn_index")
            return self.service.invoke(
                session_id=str(req.get("session_id") or ""),
                prompt=str(req.get("prompt") or ""),
                tools=tools if isinstance(tools, list) else None,
                messages=messages if isinstance(messages, list) else None,
                request_id=request_id if isinstance(request_id, str) else None,
                turn_index=turn_index
                if isinstance(turn_index, int) and not isinstance(turn_index, bool)
                else None,
            )
        if op == "cancel":
            return self.service.cancel_request(
                session_id=str(req.get("session_id") or ""),
                request_id=str(req.get("request_id") or ""),
            )
        if op == "close":
            return self.service.close_session(session_id=str(req.get("session_id") or ""))
        if op == "record_observation":
            return self.service.record_observation(
                session_id=str(req.get("session_id") or ""),
                tool_call_id=str(req.get("tool_call_id") or ""),
                content=str(req.get("content") or ""),
                invocation_id=(
                    str(req["invocation_id"])
                    if isinstance(req.get("invocation_id"), str) and req.get("invocation_id")
                    else None
                ),
                function_name=(
                    str(req["function_name"])
                    if isinstance(req.get("function_name"), str) and req.get("function_name")
                    else None
                ),
                raw_output=req.get("raw_output"),
                error=bool(req.get("error")),
            )
        return {"ok": False, "error": "unknown_op"}


def agent_service_client_call(sock_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """SDK/worker client helper."""
    from ageval.runtime.offline import is_offline_agent

    if is_offline_agent() and payload.get("op") == "invoke":
        return {"ok": False, "error": "offline_forced", "structured": None}
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(sock_path)
        _send_msg(conn, payload)
        return _recv_msg(conn)
    finally:
        conn.close()
