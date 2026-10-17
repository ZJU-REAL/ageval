#!/usr/bin/env python3
"""Stdlib in-box ACP oneshot client. Spawn entry server, drive one prompt, exit.

No ageval Core and no Python ACP SDK. Parent learns completion from this
process's exit, not from JSON-RPC framing.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    result_path: str | None = None
    if not args:
        return _emit({"ok": False, "error": "acp_oneshot_request_missing", "text": ""}, 1)
    try:
        request = json.loads(args[0])
    except json.JSONDecodeError:
        return _emit({"ok": False, "error": "acp_oneshot_request_invalid", "text": ""}, 1)
    if not isinstance(request, dict):
        return _emit({"ok": False, "error": "acp_oneshot_request_invalid", "text": ""}, 1)
    raw_path = request.get("result_path")
    if isinstance(raw_path, str) and raw_path.strip():
        result_path = raw_path.strip()
    command = request.get("acp_command")
    if not isinstance(command, list) or not command:
        return _emit(
            {"ok": False, "error": "acp_entry_missing", "text": ""},
            1,
            result_path=result_path,
        )
    prompt = str(request.get("prompt") or "")
    cwd = str(request.get("cwd") or os.getcwd())
    timeout = float(request.get("timeout_sec") or 60.0)
    model = str(request.get("model") or "entry-default")
    effort = request.get("reasoning_effort")
    effort_s = str(effort).strip() if isinstance(effort, str) and effort.strip() else None
    protocol_version = int(request.get("protocol_version") or 1)
    env = os.environ.copy()
    env.setdefault("HOME", cwd)
    try:
        payload = _run_oneshot(
            [str(part) for part in command],
            prompt=prompt,
            cwd=cwd,
            timeout=timeout,
            model=model,
            reasoning_effort=effort_s,
            protocol_version=protocol_version,
            env=env,
        )
    except TimeoutError:
        return _emit(
            {"ok": False, "error": "acp_timeout", "text": "", "model": model},
            1,
            result_path=result_path,
        )
    except Exception as exc:  # noqa: BLE001 — wrapper boundary
        return _emit(
            {
                "ok": False,
                "error": "acp_protocol_error",
                "text": "",
                "detail": f"{type(exc).__name__}:{exc}"[:300],
            },
            1,
            result_path=result_path,
        )
    return _emit(
        payload,
        0 if payload.get("ok") or payload.get("error") else 1,
        result_path=result_path,
    )


def _run_oneshot(
    command: list[str],
    *,
    prompt: str,
    cwd: str,
    timeout: float,
    model: str,
    reasoning_effort: str | None,
    protocol_version: int,
    env: dict[str, str],
) -> dict[str, Any]:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    client = _NdjsonClient(proc, timeout=timeout)
    try:
        init = client.request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "clientInfo": {"name": "ageval-acp-oneshot", "version": "0"},
            },
        )
        agent_info = init.get("agentInfo") or init.get("agent_info") or {}
        new = client.request("session/new", {"cwd": cwd, "mcpServers": []})
        session_id = str(new.get("sessionId") or new.get("session_id") or "")
        if not session_id:
            raise RuntimeError("acp_protocol_error")
        actual_model, config_options = _bind_model(client, session_id, model, new)
        actual_effort = _bind_reasoning(client, session_id, reasoning_effort, config_options)
        prompt_resp = client.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": prompt}],
            },
        )
        stop = prompt_resp.get("stopReason") or prompt_resp.get("stop_reason") or "end_turn"
        ok, error = _map_stop_reason(str(stop))
        usage = prompt_resp.get("usage") if isinstance(prompt_resp.get("usage"), dict) else None
        text = "".join(client.text_chunks)
        if any(e.get("type") == "elicitation" for e in client.events[-5:]) and not text:
            ok, error = False, "acp_elicitation_required"
        with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
            client.notify("session/cancel", {"sessionId": session_id})
            client.request("session/close", {"sessionId": session_id}, ignore_error=True)
        return {
            "ok": ok,
            "error": error,
            "text": text,
            "stop_reason": str(stop),
            "session_id": session_id,
            "protocol_version": init.get("protocolVersion") or protocol_version,
            "agent_info": agent_info if isinstance(agent_info, dict) else {},
            "actual_model": actual_model,
            "actual_reasoning_effort": actual_effort,
            "events": client.events,
            "usage": usage,
            "model": actual_model,
        }
    finally:
        client.close()


def _bind_model(
    client: _NdjsonClient,
    session_id: str,
    desired: str,
    new_session: dict[str, Any],
) -> tuple[str, Any]:
    options = new_session.get("configOptions") or new_session.get("config_options") or []
    if options:
        for opt in options:
            if not isinstance(opt, dict):
                continue
            if opt.get("category") != "model":
                continue
            config_id = opt.get("id")
            current = opt.get("currentValue") or opt.get("current_value")
            values = _select_values(opt)
            if desired in {"entry-default", ""}:
                return (str(current) if current is not None else "entry-default"), options
            if desired in values and config_id:
                resp = client.request(
                    "session/set_config_option",
                    {"sessionId": session_id, "configId": str(config_id), "value": desired},
                )
                latest = resp.get("configOptions") or resp.get("config_options") or options
                return desired, latest
            raise RuntimeError("acp_model_unavailable")
    if desired not in {"entry-default", ""}:
        raise RuntimeError("acp_model_unavailable")
    return "entry-default", options


def _bind_reasoning(
    client: _NdjsonClient,
    session_id: str,
    desired: str | None,
    config_options: Any,
) -> str | None:
    if not desired:
        return None
    ids = {"thought_level", "reasoning_effort", "reasoning", "thinking", "effort"}
    opt = None
    for item in config_options or ():
        if not isinstance(item, dict):
            continue
        if item.get("category") == "thought_level":
            opt = item
            break
        if opt is None and item.get("id") in ids:
            opt = item
    if opt is None:
        raise RuntimeError("acp_reasoning_effort_unavailable")
    config_id = opt.get("id")
    values = _select_values(opt)
    current = opt.get("currentValue") or opt.get("current_value")
    if current is not None and desired == str(current):
        return desired
    if not config_id or desired not in values:
        raise RuntimeError("acp_reasoning_effort_unavailable")
    client.request(
        "session/set_config_option",
        {"sessionId": session_id, "configId": str(config_id), "value": desired},
    )
    return desired


def _select_values(opt: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in opt.get("options") or ():
        if not isinstance(item, dict):
            continue
        grouped = item.get("options")
        own = item.get("value")
        if grouped and own is None:
            for child in grouped:
                if isinstance(child, dict) and child.get("value") is not None:
                    values.append(str(child["value"]))
            continue
        if own is not None:
            values.append(str(own))
    return values


def _map_stop_reason(stop: str) -> tuple[bool, str | None]:
    if stop in {"end_turn", "end-turn", "stop"}:
        return True, None
    mapping = {
        "max_tokens": "acp_stop_max_tokens",
        "max_turn_requests": "acp_stop_max_turn_requests",
        "refusal": "acp_stop_refusal",
        "cancelled": "acp_cancelled",
        "canceled": "acp_cancelled",
    }
    return False, mapping.get(stop, f"acp_stop_{stop}")


class _NdjsonClient:
    def __init__(self, proc: subprocess.Popen[bytes], *, timeout: float) -> None:
        self._proc = proc
        self._timeout = max(1.0, float(timeout))
        self._next_id = 0
        self._pending: dict[int, Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.text_chunks: list[str] = []
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_stdout, name="acp-oneshot-out", daemon=True
        )
        self._err = threading.Thread(target=self._drain_stderr, name="acp-oneshot-err", daemon=True)
        self._reader.start()
        self._err.start()

    def request(
        self, method: str, params: dict[str, Any], *, ignore_error: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            inbox: Queue[dict[str, Any]] = Queue()
            self._pending[msg_id] = inbox
        self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        try:
            msg = inbox.get(timeout=self._timeout)
        except Empty as exc:
            raise TimeoutError("acp_timeout") from exc
        if "error" in msg and not ignore_error:
            err = msg.get("error")
            raise RuntimeError(str(err) if err else "acp_protocol_error")
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
        self._alive = False
        if self._proc.poll() is None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                self._proc.terminate()
                self._proc.wait(timeout=3)
            with contextlib.suppress(OSError):
                self._proc.kill()
        if self._proc.stdin is not None:
            with contextlib.suppress(OSError):
                self._proc.stdin.close()

    def _send(self, message: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise RuntimeError("acp_protocol_error")
        line = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        stdin.write(line)
        stdin.flush()

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            return
        while self._alive:
            line = stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            self._dispatch(msg)

    def _drain_stderr(self) -> None:
        stderr = self._proc.stderr
        if stderr is None:
            return
        while self._alive:
            chunk = stderr.readline()
            if not chunk:
                break

    def _dispatch(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        msg_id = msg.get("id")
        if isinstance(method, str) and msg_id is not None:
            self._handle_agent_request(method, msg_id, msg.get("params") or {})
            return
        if isinstance(method, str):
            self._handle_notification(method, msg.get("params") or {})
            return
        if msg_id is not None:
            try:
                key = int(msg_id)
            except (TypeError, ValueError):
                return
            with self._lock:
                inbox = self._pending.pop(key, None)
            if inbox is not None:
                inbox.put(msg)

    def _handle_agent_request(self, method: str, msg_id: Any, params: Any) -> None:
        params = params if isinstance(params, dict) else {}
        if method == "session/request_permission":
            option_id = _auto_approve(params.get("options") or [])
            decision = {
                "type": "permission_decision",
                "session_id": params.get("sessionId") or params.get("session_id"),
                "outcome": "selected",
                "policy": "batch_auto_approve",
                "option_id": option_id,
                "source": "acp-oneshot",
            }
            self.events.append(decision)
            self._reply(
                msg_id,
                {"outcome": {"outcome": "selected", "optionId": option_id}},
            )
            return
        if method == "elicitation/create":
            self.events.append(
                {
                    "type": "elicitation",
                    "action": "decline",
                    "policy": "batch_decline",
                    "source": "acp-oneshot",
                }
            )
            self._reply(msg_id, {"action": "decline"})
            return
        self._reply(msg_id, {}, error={"code": -32601, "message": method})

    def _handle_notification(self, method: str, params: Any) -> None:
        params = params if isinstance(params, dict) else {}
        if method != "session/update":
            return
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        session_upd = update.get("sessionUpdate") or update.get("session_update")
        content = update.get("content") if isinstance(update.get("content"), dict) else {}
        text = content.get("text") if isinstance(content.get("text"), str) else None
        event: dict[str, Any] = {
            "type": "session_update",
            "session_id": params.get("sessionId") or params.get("session_id"),
            "update": update,
            "source": "acp-oneshot",
        }
        if session_upd in {"agent_message_chunk", "agent_message"} and text:
            event["text"] = text
            event["channel"] = "assistant"
            self.text_chunks.append(text)
        elif session_upd in {"agent_thought_chunk", "agent_thought"} and text:
            event["text"] = text
            event["channel"] = "thought"
        self.events.append(event)

    def _reply(
        self, msg_id: Any, result: dict[str, Any], *, error: dict[str, Any] | None = None
    ) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        self._send(payload)


def _auto_approve(options: Any) -> str:
    rows = list(options) if isinstance(options, list) else []
    for opt in rows:
        if not isinstance(opt, dict):
            continue
        kind = opt.get("kind")
        oid = opt.get("optionId") or opt.get("option_id")
        if kind in {"allow_once", "allow_always", "allow", "selected"} or (
            isinstance(oid, str) and "allow" in oid.lower()
        ):
            return str(oid or "allow")
    if rows and isinstance(rows[0], dict):
        first = rows[0].get("optionId") or rows[0].get("option_id")
        if first:
            return str(first)
    return "allow"


def _emit(payload: dict[str, Any], code: int, *, result_path: str | None = None) -> int:
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(line, encoding="utf-8")
    sys.stdout.write(line)
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
