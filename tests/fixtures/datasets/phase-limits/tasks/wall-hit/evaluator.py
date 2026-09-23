"""Score the harvested attempt. A killed run is still a verdict."""

from __future__ import annotations


def evaluate(inputs: dict) -> dict:
    del inputs
    return {"status": "FAIL", "score": 0.3, "metrics": {"tests_passed": 3, "tests_total": 10}}
