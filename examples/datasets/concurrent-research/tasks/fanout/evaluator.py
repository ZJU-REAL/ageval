"""Score the published report against the corpus sentences.

The model's transcript is not the verdict. PASS is this comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    arts = inputs.get("artifacts") or {}
    report_path = arts.get("report")
    if not report_path:
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "report_missing"}}
    path = Path(str(report_path))
    if not path.is_file():
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "report_missing"}}
    report = json.loads(path.read_text(encoding="utf-8"))
    gold_path = Path(str(inputs["evaluation_dir"])) / "expected.json"
    expected = json.loads(gold_path.read_text(encoding="utf-8"))
    blob = json.dumps(report, ensure_ascii=False)
    missing = [topic for topic, sentence in expected.items() if sentence not in blob]
    return {
        "status": "PASS" if not missing else "FAIL",
        "score": 1.0 if not missing else 0.0,
        "metrics": {"missing": missing},
    }
