"""Score hello.txt. The trajectory does not decide PASS."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    arts = inputs.get("artifacts") or {}
    raw = arts.get("hello")
    if not raw:
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "hello_missing"}}
    path = Path(str(raw))
    if not path.is_file():
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "hello_missing"}}
    text = path.read_text(encoding="utf-8")
    ok = text == "hello\n"
    return {
        "status": "PASS" if ok else "FAIL",
        "score": 1.0 if ok else 0.0,
        "metrics": {"exact": 1 if ok else 0},
    }
