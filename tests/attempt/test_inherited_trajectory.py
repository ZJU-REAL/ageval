"""A finished-invoke fork keeps the parent's display trajectory."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases.record import inherited_display_rows


def test_completed_invoke_fork_copies_parent_trajectory(tmp_path: Path) -> None:
    parent = tmp_path / ".ageval" / "runs" / "attempt_parent"
    parent.mkdir(parents=True)
    row = {"type": "tool_call", "content": "ls"}
    (parent / "trajectory.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    ctx = SimpleNamespace(
        dataset_root=tmp_path,
        fork_checkpoint_seq=7,
        fork_provenance={"parent_attempt_id": "attempt_parent"},
        activity=SimpleNamespace(
            records=[SimpleNamespace(seq=7, kind="invoke", status="completed")]
        ),
    )
    copied = inherited_display_rows(cast(AttemptCtx, ctx))
    assert copied[0]["content"] == "ls"
    assert copied[0]["inherited"] is True


def test_mid_invoke_cut_does_not_copy_later_parent_lines(tmp_path: Path) -> None:
    parent = tmp_path / ".ageval" / "runs" / "attempt_parent"
    parent.mkdir(parents=True)
    (parent / "trajectory.jsonl").write_text('{"type":"tool_call"}\n', encoding="utf-8")
    ctx = SimpleNamespace(
        dataset_root=tmp_path,
        fork_checkpoint_seq=6,
        fork_provenance={"parent_attempt_id": "attempt_parent"},
        activity=SimpleNamespace(
            records=[SimpleNamespace(seq=6, kind="tool_call", status="completed")]
        ),
    )
    assert inherited_display_rows(cast(AttemptCtx, ctx)) == []
