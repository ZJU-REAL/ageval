"""Two observational checks. Top-level PASS is independent of the FAIL row."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval_sdk import evaluation_check


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = (inputs.get("artifacts") or {}).get("result")
    if not raw:
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "result_missing"}}
    data = json.loads(Path(str(raw)).read_text(encoding="utf-8"))
    ok = data.get("ok") is True
    return {
        "status": "PASS" if ok else "FAIL",
        "score": 1.0 if ok else 0.0,
        "metrics": {"exact": 1 if ok else 0},
        "checks": [
            evaluation_check(
                "audit",
                title="schema audit",
                status="FAIL",
                score=0.0,
                script="evaluation/audit.py",
                stdout="schema mismatch (observational)",
            ),
            evaluation_check(
                "files",
                title="artifact files",
                status="PASS" if ok else "FAIL",
                score=1.0 if ok else 0.0,
                script="evaluator.py",
                stdout="result.json present" if ok else "result.json missing",
            ),
        ],
    }
