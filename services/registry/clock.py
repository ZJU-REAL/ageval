"""Monotonic-enough wall clock for Registry timestamps (epoch seconds)."""

from __future__ import annotations

import time


def now() -> float:
    return time.time()
