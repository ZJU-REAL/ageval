"""Sealed evidence documents match the writers, and the generated TS matches the schema."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ageval.application.phase_timing import TIMING_SCHEMA, timing_from_facts
from ageval.attempt.ctx import AttemptCtx, PhaseFact
from ageval.evaluation.bind import STATUS_ERROR, STATUS_FAIL, STATUS_PASS, AttemptResult
from ageval.evidence.documents import json_schema
from ageval.evidence.schema import SUMMARY_SCHEMA_VERSION
from ageval.evidence.store import AttemptEvidenceStore
from ageval.evidence.trajectory import turn_rows

ROOT = Path(__file__).resolve().parents[2]


def _defs() -> dict[str, Any]:
    return json_schema()["$defs"]


def _check(node: dict[str, Any], value: Any, defs: dict[str, Any]) -> None:
    if "anyOf" in node:
        errors: list[str] = []
        for part in node["anyOf"]:
            try:
                _check(part, value, defs)
            except AssertionError as exc:
                errors.append(str(exc))
            else:
                return
        raise AssertionError(errors)
    if "oneOf" in node:
        matched = 0
        for part in node["oneOf"]:
            try:
                _check(part, value, defs)
            except AssertionError:
                continue
            matched += 1
        assert matched == 1, matched
        return
    if "$ref" in node:
        _check(defs[node["$ref"].rsplit("/", 1)[-1]], value, defs)
        return
    if "const" in node:
        assert value == node["const"]
        return
    if "enum" in node:
        assert value in node["enum"]
        return
    kind = node.get("type")
    if kind == "null":
        assert value is None
        return
    if kind == "string":
        assert isinstance(value, str) and not isinstance(value, bool)
        return
    if kind == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)
        return
    if kind == "number":
        assert isinstance(value, int | float) and not isinstance(value, bool)
        return
    if kind == "boolean":
        assert isinstance(value, bool)
        return
    if kind == "array":
        assert isinstance(value, list)
        for item in value:
            _check(node["items"], item, defs)
        return
    if kind == "object":
        assert isinstance(value, dict)
        props: dict[str, Any] = node.get("properties", {})
        if node.get("additionalProperties") is False:
            assert set(value) <= set(props)
        for key in node.get("required", ()):
            assert key in value
        for key, item in value.items():
            if key in props:
                _check(props[key], item, defs)
        if "minProperties" in node:
            assert len(value) >= node["minProperties"]
        return
    raise AssertionError(node)


def _result() -> AttemptResult:
    return AttemptResult(
        status=STATUS_ERROR,
        score=None,
        metrics={"checks": 0},
        error={"phase": "evaluate", "title": "evaluator_invalid_status", "message": "no verdict"},
        cleanup_warning=None,
        evidence_path=".ageval/runs/att-1",
        kind="local",
        capabilities_used=("filesystem",),
        agent_invocations=1,
        logs=None,
        limit=None,
    )


def test_result_json_keeps_nulls_and_omits_facts() -> None:
    defs = _defs()
    doc = _result().as_dict()
    props = set(defs["AttemptResultDocument"]["properties"])
    required = set(defs["AttemptResultDocument"]["required"])
    assert required <= set(doc) <= props
    assert "fork" not in doc
    assert "facts" not in doc
    assert doc["score"] is None
    assert doc["cleanup_warning"] is None
    assert doc["limit"] is None
    assert doc["logs"] == doc["evidence_path"]
    _check(defs["AttemptResultDocument"], doc, defs)
    assert {STATUS_PASS, STATUS_FAIL, STATUS_ERROR} == set(
        defs["AttemptResultDocument"]["properties"]["status"]["enum"]
    )


def test_summary_and_terminal_follow_omit_none(tmp_path: Path) -> None:
    defs = _defs()

    class _Facts:
        phase_facts: list[PhaseFact]

    holder = _Facts()
    holder.phase_facts = [
        PhaseFact(
            phase="run",
            name="phase_finished",
            detail={
                "phase": "run",
                "duration_ms": 12,
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
            },
        ),
        PhaseFact(phase="run", name="note", detail={}),
    ]
    facts = AttemptCtx.facts_as_list(holder)  # type: ignore[arg-type]
    assert "detail" not in facts[1]
    timing = timing_from_facts(facts)
    assert timing["schema"] == TIMING_SCHEMA
    assert defs["PhaseTimingDocument"]["properties"]["schema"]["const"] == TIMING_SCHEMA
    bare = timing_from_facts(
        [{"name": "phase_finished", "detail": {"phase": "evaluate", "duration_ms": 1}}]
    )
    assert "started_at" not in bare
    assert "finished_at" not in bare

    dataset = tmp_path / "dataset"
    root = dataset / ".ageval" / "runs" / "att-1"
    store = AttemptEvidenceStore(
        root=root,
        attempt_id="att-1",
        run_id="run-1",
        dataset_root=dataset,
    )
    store.write_summary(
        {
            "result": _result().as_dict(),
            "facts": facts,
            "phase_timing": timing,
            "keep_vendor_raw": False,
        }
    )
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["schema"] == SUMMARY_SCHEMA_VERSION
    assert "extra" not in summary
    _check({"$ref": "#/$defs/SummaryDocument"}, summary, defs)

    rows = turn_rows(
        prompt="p",
        events=(),
        final_text="done",
        structured=None,
        usage={"prompt_tokens": 3, "completion_tokens": 1},
        ok=True,
        error=None,
        metadata=None,
    )
    terminal = rows[-1]
    assert terminal["type"] == "terminal"
    assert "extra" not in terminal
    assert "elapsed_ms" not in terminal
    assert "profile_id" not in terminal
    assert terminal["usage"]["prompt_tokens"] == 3
    _check({"$ref": "#/$defs/TerminalRow"}, terminal, defs)

    with_clock = turn_rows(
        prompt="p",
        events=(),
        final_text="",
        structured=None,
        usage={"unavailable": "lost_on_timeout", "prompt_tokens": 2},
        ok=False,
        error="acp_idle_timeout",
        metadata={"elapsed_ms": 10, "profile_id": "solver", "stop_reason": "idle"},
    )[-1]
    assert with_clock["elapsed_ms"] == 10.0
    assert with_clock["profile_id"] == "solver"
    _check({"$ref": "#/$defs/TerminalRow"}, with_clock, defs)

    rejected = False
    try:
        _check(
            {"$ref": "#/$defs/TerminalUsage"},
            {"input_tokens": 1},
            defs,
        )
    except AssertionError:
        rejected = True
    assert rejected


def test_generated_typescript_matches_schema() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/gen_evidence_ts.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = (ROOT / "apps/shared/lib/evidence.gen.ts").read_text(encoding="utf-8")
    assert "export type TerminalUsage" in text
    assert "Do not edit." in text
