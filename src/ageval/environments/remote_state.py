"""Recovery state for environments that do not bind-mount ``/attempt``.

``e2b``, ``daytona``, and ``ssh`` run ``checkpoint_sync.py`` inside the
environment. The parent downloads the delta and folds it into the local
attempt directory before the next checkpoint.
"""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Any

from ageval.environments.protocol import ProbeStatus

CHECKPOINT_SYNC_NAME = "checkpoint_sync.py"
_STATE = "/attempt/.ageval-state"

CHECKPOINT_SYNC_SCRIPT = r'''
import json, os, sys, tarfile
from pathlib import Path

ROOT = Path(os.environ.get("AGEVAL_BOX_ROOT") or "/attempt")
ROOTS = ("workspace", "home", "artifacts")
SKIP = {
    "home/.codex/auth.json",
    "home/.claude/.credentials.json",
    "home/.pi/agent/auth.json",
    "home/.local/share/opencode/auth.json",
    "home/.grok/auth.json",
}


def _rel(path, root):
    return str(path.relative_to(root)).replace(os.sep, "/")


def _index(state):
    raw = state / "stat_index.json"
    if not raw.is_file():
        return {}
    try:
        data = json.loads(raw.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _record(request_id):
    state = ROOT / ".ageval-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "inflight.request").write_text(request_id, encoding="utf-8")
    (state / "inflight.pid").write_text(str(os.getpid()) + "\n", encoding="utf-8")


def _finish(request_id, code):
    state = ROOT / ".ageval-state"
    state.mkdir(parents=True, exist_ok=True)
    payload = {"request_id": request_id, "exit_code": code, "stdout": "", "stderr": ""}
    (state / "last_exit.json").write_text(json.dumps(payload), encoding="utf-8")
    for name in ("inflight.pid", "inflight.request"):
        path = state / name
        if path.exists():
            path.unlink()


def _dump():
    state = ROOT / ".ageval-state"
    def text(name):
        path = state / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    cursor = {}
    raw = text("cursor.json")
    if raw:
        try:
            cursor = json.loads(raw)
        except json.JSONDecodeError:
            cursor = {}
    last = {}
    raw_last = text("last_exit.json")
    if raw_last:
        try:
            last = json.loads(raw_last)
        except json.JSONDecodeError:
            last = {}
    pid_text = text("inflight.pid").strip()
    pid = int(pid_text) if pid_text.isdigit() else None
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
        except PermissionError:
            alive = True
        except OSError:
            alive = False
        else:
            alive = True
    print(json.dumps({
        "nonce": text("nonce").strip(),
        "cursor": cursor,
        "inflight_pid": pid if alive else None,
        "inflight_request": text("inflight.request").strip() if alive else "",
        "last_exit": last,
    }))


def _pack(out_path):
    root = ROOT
    state = ROOT / ".ageval-state"
    state.mkdir(parents=True, exist_ok=True)
    previous = _index(state)
    current = {}
    changed = []
    for folder in ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = folder + "/" + _rel(path, base)
            if rel in SKIP:
                continue
            st = path.stat()
            stamp = [st.st_mtime_ns, st.st_size]
            current[rel] = stamp
            if previous.get(rel) != stamp:
                changed.append((rel, path, st.st_mode))
    with tarfile.open(out_path, "w") as archive:
        for rel, path, mode in changed:
            archive.add(path, arcname=rel)
    digest = {}
    for rel, path, mode in changed:
        digest[rel] = [path.stat().st_mtime_ns, path.stat().st_size]
    previous.update(digest)
    (state / "stat_index.json").write_text(json.dumps(previous), encoding="utf-8")


def main(argv):
    if len(argv) >= 3 and argv[1] == "record":
        _record(argv[2])
        return 0
    if len(argv) >= 3 and argv[1] == "finish":
        _finish(argv[2], int(argv[3]) if len(argv) > 3 else 0)
        return 0
    if len(argv) >= 2 and argv[1] == "dump":
        _dump()
        return 0
    if len(argv) >= 3 and argv[1] == "pack":
        _pack(argv[2])
        return 0
    print("usage: checkpoint_sync.py dump|pack|record|finish", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def parse_state_document(raw: str) -> ProbeStatus:
    """Turn one ``dump`` document into a probe result. Empty input is absent."""
    text = raw.strip()
    if not text:
        return ProbeStatus(status="absent")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ProbeStatus(status="absent")
    if not isinstance(data, dict):
        return ProbeStatus(status="absent")
    nonce = data.get("nonce") if isinstance(data.get("nonce"), str) and data.get("nonce") else None
    cursor = data.get("cursor") if isinstance(data.get("cursor"), dict) else {}
    seq = cursor.get("seq")
    request = cursor.get("request_id")
    last = data.get("last_exit") if isinstance(data.get("last_exit"), dict) else None
    inflight = data.get("inflight_pid")
    busy = isinstance(inflight, int) and not isinstance(inflight, bool)
    return ProbeStatus(
        status="busy" if busy else "idle",
        nonce=nonce,
        cursor_seq=seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        cursor_request_id=request if isinstance(request, str) and request else None,
        inflight_request_id=(
            data.get("inflight_request")
            if isinstance(data.get("inflight_request"), str) and data.get("inflight_request")
            else None
        ),
        last_exit=last,
    )


def apply_checkpoint_tar(box: Path, blob: bytes) -> int:
    """Extract a remote delta into the local attempt directory. Returns file count."""
    if not blob:
        return 0
    count = 0
    with tarfile.open(fileobj=BytesIO(blob), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            rel = member.name.replace("\\", "/")
            if rel.startswith("/") or ".." in rel.split("/"):
                continue
            target = box / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target.write_bytes(extracted.read())
            count += 1
    return count


def state_command(action: str, *args: str) -> list[str]:
    """Argv that runs the uploaded helper inside the environment."""
    return ["python3", f"{_STATE}/{CHECKPOINT_SYNC_NAME}", action, *args]


_RESTORE_DIRS = (
    ("workspace", "/attempt/workspace"),
    ("home", "/attempt/home"),
    ("artifacts", "/attempt/artifacts"),
    (".ageval-state", "/attempt/.ageval-state"),
)


async def push_restored_tree(host: Any, box: Path) -> None:
    """Upload a locally restored attempt tree into a remote environment."""
    upload = getattr(host, "upload", None)
    if not callable(upload):
        return
    for name, remote in _RESTORE_DIRS:
        local = box / name
        if not local.is_dir():
            continue
        if not any(local.rglob("*")):
            continue
        await upload(local, remote)


def wrapper_line(request_id: str, inner: str) -> str:
    """Shell that records the in-flight request around ``inner``."""
    quoted = json.dumps(request_id)
    script = f"{_STATE}/{CHECKPOINT_SYNC_NAME}"
    return (
        f"python3 {script} record {quoted}; "
        f"{inner}; ec=$?; "
        f"python3 {script} finish {quoted} $ec; "
        "exit $ec"
    )
