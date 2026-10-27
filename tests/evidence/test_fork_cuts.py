"""Fork-cut classification for retained checkpoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from ageval.application.checkpoints import list_checkpoints
from ageval.cli.main import app
from ageval.evidence.activity import ActivityLog
from ageval.evidence.checkpoints import CHECKPOINT_FORMAT
from ageval.evidence.fork_cuts import list_fork_cuts


def _header() -> dict[str, object]:
    return {
        "run_id": "run01",
        "trial_id": "trial01",
        "attempt_id": "attempt01",
        "task_id": "demo",
        "attempt_index": 0,
        "suite_run_id": None,
        "locked_config_digest": "sha256:abc",
        "environment_kind": "docker",
        "environment_nonce": "nce_abc",
        "environment_handle": None,
    }


def _session(kind: str = "miniswe", session_id: str = "sess_solver_1") -> dict[str, object]:
    return {
        "session_id": session_id,
        "profile_id": "solver",
        "actor_id": "default",
        "environment": "main",
        "executor_kind": kind,
        "native_session_id": None,
    }


def _phase(name: str, *, seq: int | None = None, status: str = "completed") -> dict[str, object]:
    if status == "in_flight":
        return {"phase": name}
    return {
        "phase": name,
        "elapsed_ms": 1,
        "limit_reached": None,
        "checkpoint_seq": seq,
    }


def _tool(seq: int, session_id: str = "sess_solver_1") -> dict[str, object]:
    return {
        "session_id": session_id,
        "invoke_request_id": "req_1",
        "tool_call_id": f"call_{seq}",
        "outcome": "ok",
        "exit_code": 0,
        "content": "ok",
        "stderr": "",
        "raw_output": "",
        "checkpoint_seq": seq,
    }


def _append(
    log: ActivityLog, kind: str, status: str, payload: dict[str, object], request: str
) -> None:
    log.append(request_id=request, kind=kind, status=status, payload=payload)


def _manifest(attempt: Path, seq: int, *, blob: bool = True) -> None:
    digest = hashlib.sha256(f"blob-{seq}".encode()).hexdigest()
    root = attempt / "checkpoints"
    path = root / f"seq_{seq:06d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries: dict[str, object] = {}
    if blob:
        blob_path = root / "blobs" / digest[:2] / digest
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(f"blob-{seq}".encode())
        entries["workspace/note.txt"] = {
            "kind": "file",
            "mode": 0o644,
            "size": 6,
            "mtime_ns": 1,
            "sha256": digest,
        }
    path.write_text(
        json.dumps(
            {
                "format": CHECKPOINT_FORMAT,
                "seq": seq,
                "created_at": "2026-01-01T00:00:00.000Z",
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def _attempt(tmp_path: Path, executor: str = "miniswe") -> Path:
    attempt = tmp_path / "attempt01"
    log = ActivityLog.open(attempt / "activity.jsonl")
    _append(log, "attempt", "completed", _header(), "att")
    _append(
        log, "phase", "in_flight", _phase("environment", status="in_flight"), "phase_environment"
    )
    _append(log, "phase", "completed", _phase("environment", seq=3), "phase_environment")
    _manifest(attempt, 3)
    _append(log, "phase", "in_flight", _phase("run", status="in_flight"), "phase_run")
    _append(log, "session", "completed", _session(executor), "sess")
    _append(log, "tool_call", "completed", _tool(6), "tool_6")
    _manifest(attempt, 6)
    return attempt


def test_run_phase_cut_is_forkable_and_environment_cut_is_not(tmp_path: Path) -> None:
    listing = list_fork_cuts(_attempt(tmp_path), attempt_id="attempt01")
    by_seq = {cut.seq: cut for cut in listing.cuts}
    assert listing.error is None
    assert by_seq[3].forkable is False
    assert by_seq[3].reason == "not_run_phase"
    assert by_seq[6].forkable is True
    assert by_seq[6].reason is None
    assert by_seq[6].state == "available"
    assert by_seq[6].phase == "run"
    assert by_seq[6].kind == "tool_call"


def test_seal_and_gold_and_unsupported_and_multi_session(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path, executor="acp")
    log = ActivityLog.open(attempt / "activity.jsonl")
    _append(log, "session", "completed", _session("miniswe", "sess_solver_2"), "sess2")
    _append(log, "tool_call", "completed", _tool(8, "sess_solver_2"), "tool_8")
    _manifest(attempt, 8)
    _append(log, "phase", "completed", _phase("seal_run"), "phase_seal_run")
    _append(log, "phase", "in_flight", _phase("evaluate", status="in_flight"), "phase_evaluate")
    _append(log, "phase", "completed", _phase("evaluate", seq=11), "phase_evaluate")
    _manifest(attempt, 11)

    by_seq = {cut.seq: cut for cut in list_fork_cuts(attempt, attempt_id="attempt01").cuts}
    assert by_seq[6].reason == "continuation_unsupported"
    assert by_seq[8].reason == "multi_session"
    assert by_seq[11].reason == "gold_exposed"


def test_solver_sealed_before_gold(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    log = ActivityLog.open(attempt / "activity.jsonl")
    _append(log, "phase", "completed", _phase("seal_run", seq=7), "phase_seal_run")
    _manifest(attempt, 7)
    cut = next(
        item for item in list_fork_cuts(attempt, attempt_id="attempt01").cuts if item.seq == 7
    )
    assert cut.reason == "solver_sealed"
    assert cut.forkable is False


def test_missing_blob_is_not_restorable(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    digest = hashlib.sha256(b"blob-6").hexdigest()
    (attempt / "checkpoints" / "blobs" / digest[:2] / digest).unlink()
    cut = next(
        item for item in list_fork_cuts(attempt, attempt_id="attempt01").cuts if item.seq == 6
    )
    assert cut.state == "incomplete"
    assert cut.reason == "state_not_restorable"
    assert cut.forkable is False


def test_missing_bundle_and_cli(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    attempt = dataset / ".ageval" / "runs" / "attempt01"
    attempt.mkdir(parents=True)
    (attempt / "result.json").write_text("{}", encoding="utf-8")
    missing = list_checkpoints(dataset, "attempt01")
    assert missing.error == "recovery_state_missing"
    assert list_checkpoints(dataset, "../secret").error == "unknown_run"

    runner = CliRunner()
    refused = runner.invoke(app, ["checkpoints", str(dataset), "--run", "attempt01", "--json"])
    assert refused.exit_code == 2
    assert json.loads(refused.output)["error"] == "recovery_state_missing"

    _attempt(dataset / ".ageval" / "runs")
    listed = runner.invoke(app, ["checkpoints", str(dataset), "--run", "attempt01", "--json"])
    assert listed.exit_code == 0
    body = json.loads(listed.output)
    forkable = [row for row in body["checkpoints"] if row["forkable"]]
    assert [row["seq"] for row in forkable] == [6]
