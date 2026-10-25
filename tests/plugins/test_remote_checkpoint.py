"""Remote checkpoint deltas and probe parsing. No cloud credentials required."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from ageval.environments.protocol import BoxSpec
from ageval.environments.remote_state import (
    CHECKPOINT_SYNC_SCRIPT,
    apply_checkpoint_tar,
    parse_state_document,
)
from ageval.plugins.contrib.daytona.host import DaytonaHost
from ageval.plugins.contrib.e2b.host import E2BHost
from ageval.plugins.contrib.ssh.host import SSHHost


def _spec(tmp_path: Path) -> BoxSpec:
    return BoxSpec(attempt_root=tmp_path, task_root=tmp_path, repo_root=tmp_path)


def test_dump_document_marks_an_inflight_pid_busy() -> None:
    raw = json.dumps(
        {
            "nonce": "nce_1",
            "cursor": {"seq": 4, "request_id": "seq_4"},
            "inflight_pid": 42,
            "inflight_request": "call_1",
            "last_exit": None,
        }
    )
    status = parse_state_document(raw)
    assert status.status == "busy"
    assert status.nonce == "nce_1"
    assert status.cursor_seq == 4
    assert status.inflight_request_id == "call_1"


def test_checkpoint_script_packs_only_changed_files(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    (root / "workspace").mkdir(parents=True)
    (root / "workspace" / "note.txt").write_text("one\n", encoding="utf-8")
    script = tmp_path / "checkpoint_sync.py"
    script.write_text(CHECKPOINT_SYNC_SCRIPT, encoding="utf-8")
    env = os.environ.copy()
    env["AGEVAL_BOX_ROOT"] = str(root)
    out = tmp_path / "delta.tar"
    first = subprocess.run(
        [sys.executable, str(script), "pack", str(out)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    box = tmp_path / "box"
    assert apply_checkpoint_tar(box, out.read_bytes()) == 1
    assert (box / "workspace" / "note.txt").read_text(encoding="utf-8") == "one\n"
    second = subprocess.run(
        [sys.executable, str(script), "pack", str(out)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert apply_checkpoint_tar(tmp_path / "again", out.read_bytes()) == 0


def test_remote_probe_without_a_handle_is_absent(tmp_path: Path) -> None:
    e2b = E2BHost(spec=_spec(tmp_path / "e2b"))
    daytona = DaytonaHost(spec=_spec(tmp_path / "daytona"))
    ssh = SSHHost(spec=_spec(tmp_path / "ssh"), options={"host": "example.invalid"})
    assert asyncio.run(e2b.probe({})).status == "absent"
    assert asyncio.run(daytona.probe({})).status == "absent"
    assert asyncio.run(ssh.probe({})).status == "absent"
    assert e2b.runtime_handle() == {}
    assert daytona.runtime_handle() == {}
