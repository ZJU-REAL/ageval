"""In-box recovery files under ``/attempt/.ageval-state``.

``local`` and ``docker`` keep this directory on the host bind root. Remote
kinds read the same names through ``exec`` / ``download``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ageval.environments.protocol import ProbeStatus

STATE_DIR_NAME = ".ageval-state"
NONCE_NAME = "nonce"
CURSOR_NAME = "cursor.json"
INFLIGHT_PID_NAME = "inflight.pid"
INFLIGHT_REQUEST_NAME = "inflight.request"
INFLIGHT_OUTPUT_NAME = "inflight.output"
LAST_EXIT_NAME = "last_exit.json"


def state_dir(box: Path) -> Path:
    return box / STATE_DIR_NAME


def ensure_state_dir(box: Path) -> Path:
    path = state_dir(box)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_nonce(box: Path, nonce: str) -> None:
    root = ensure_state_dir(box)
    (root / NONCE_NAME).write_text(nonce, encoding="utf-8")


def read_nonce(box: Path) -> str | None:
    path = state_dir(box) / NONCE_NAME
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def write_cursor(box: Path, *, seq: int, request_id: str) -> None:
    root = ensure_state_dir(box)
    _atomic_json(root / CURSOR_NAME, {"seq": seq, "request_id": request_id})


def read_cursor(box: Path) -> tuple[int | None, str | None]:
    data = _read_json(state_dir(box) / CURSOR_NAME)
    if data is None:
        return None, None
    seq = data.get("seq")
    request_id = data.get("request_id")
    cursor_seq = seq if isinstance(seq, int) and not isinstance(seq, bool) else None
    cursor_request = request_id if isinstance(request_id, str) and request_id else None
    return cursor_seq, cursor_request


def write_inflight(box: Path, *, pid: int, request_id: str) -> None:
    root = ensure_state_dir(box)
    (root / INFLIGHT_PID_NAME).write_text(f"{pid}\n", encoding="utf-8")
    (root / INFLIGHT_REQUEST_NAME).write_text(request_id, encoding="utf-8")


def clear_inflight(box: Path) -> None:
    root = state_dir(box)
    for name in (INFLIGHT_PID_NAME, INFLIGHT_REQUEST_NAME):
        path = root / name
        if path.is_file():
            path.unlink()


def read_inflight(box: Path) -> tuple[int | None, str | None]:
    root = state_dir(box)
    pid_path = root / INFLIGHT_PID_NAME
    if not pid_path.is_file():
        return None, None
    raw = pid_path.read_text(encoding="utf-8").strip()
    try:
        pid = int(raw)
    except ValueError:
        return None, None
    request_path = root / INFLIGHT_REQUEST_NAME
    request_id = request_path.read_text(encoding="utf-8").strip() if request_path.is_file() else ""
    return pid, request_id or None


def write_last_exit(box: Path, payload: dict[str, Any]) -> None:
    root = ensure_state_dir(box)
    _atomic_json(root / LAST_EXIT_NAME, payload)
    clear_inflight(box)


def read_last_exit(box: Path) -> dict[str, Any] | None:
    return _read_json(state_dir(box) / LAST_EXIT_NAME)


def read_partial_output(box: Path) -> str | None:
    path = state_dir(box) / INFLIGHT_OUTPUT_NAME
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def host_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def probe_box(box: Path, *, pid_alive: Callable[[int], bool]) -> ProbeStatus:
    """Classify a box directory. ``pid_alive`` receives the inflight pid."""
    if not box.is_dir():
        return ProbeStatus(status="absent")
    nonce = read_nonce(box)
    cursor_seq, cursor_request = read_cursor(box)
    last_exit = read_last_exit(box)
    pid, request_id = read_inflight(box)
    if pid is not None and bool(pid_alive(pid)):
        return ProbeStatus(
            status="busy",
            nonce=nonce,
            cursor_seq=cursor_seq,
            cursor_request_id=cursor_request,
            inflight_request_id=request_id,
            last_exit=last_exit,
        )
    return ProbeStatus(
        status="idle",
        nonce=nonce,
        cursor_seq=cursor_seq,
        cursor_request_id=cursor_request,
        inflight_request_id=None,
        last_exit=last_exit,
    )


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
