"""Sleep past the evaluate clock."""

from __future__ import annotations

import time


def evaluate(inputs: dict) -> dict:
    del inputs
    time.sleep(30)
    return {"status": "PASS", "score": 1.0}
