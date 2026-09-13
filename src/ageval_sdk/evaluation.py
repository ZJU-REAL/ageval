"""Optional evaluator helpers. Observational — never PASS."""

from __future__ import annotations

import math
from typing import Any


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def evaluation_check(
    check_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
    score: float | None = None,
    script: str | None = None,
    environment: str | None = None,
    exit_code: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    exec_result: Any = None,
) -> dict[str, Any]:
    """Build one ``checks`` row for the evaluator return object.

    Parent persists well-formed rows as ``evaluation/checks.json``. This helper
    does not bind PASS, write evidence, or invent rows from ``scoring.exec``.
    """
    if not isinstance(check_id, str) or not check_id.strip():
        raise ValueError("evaluation_check id must be a non-empty string")
    row: dict[str, Any] = {"id": check_id.strip()}
    if isinstance(title, str) and title.strip():
        row["title"] = title.strip()
    if isinstance(status, str) and status.strip():
        row["status"] = status.strip()
    if isinstance(score, int | float) and not isinstance(score, bool):
        number = float(score)
        if math.isfinite(number):
            row["score"] = number
    if isinstance(script, str) and script.strip():
        row["script"] = script.strip()
    if isinstance(environment, str) and environment.strip():
        row["environment"] = environment.strip()
    if exec_result is not None:
        if exit_code is None:
            exit_code = getattr(exec_result, "exit_code", None)
        if stdout is None:
            stdout = getattr(exec_result, "stdout", None)
        if stderr is None:
            stderr = getattr(exec_result, "stderr", None)
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        row["exit_code"] = exit_code
    stdout_text = _as_text(stdout)
    if stdout_text is not None:
        row["stdout"] = stdout_text
    stderr_text = _as_text(stderr)
    if stderr_text is not None:
        row["stderr"] = stderr_text
    return row
