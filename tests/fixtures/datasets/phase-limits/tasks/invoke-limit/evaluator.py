from __future__ import annotations


def evaluate(inputs: dict) -> dict:
    del inputs
    return {"status": "FAIL", "score": 0.2, "metrics": {"quota": True}}
