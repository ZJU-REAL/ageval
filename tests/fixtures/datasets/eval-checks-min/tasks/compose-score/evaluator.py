"""Compose: observational checks plus judge invoke. Bind still uses this return."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ageval_sdk import evaluation_check


async def _invoke(agent: Any, prompt: str) -> Any:
    async with agent.session("judge") as session:
        return await session.invoke(prompt)


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = (inputs.get("artifacts") or {}).get("result")
    if not raw:
        return {"status": "FAIL", "score": 0.0, "metrics": {"reason": "result_missing"}}
    data = json.loads(Path(str(raw)).read_text(encoding="utf-8"))
    gold = Path(str(inputs["evaluation_dir"])) / "expected.json"
    gold_text = gold.read_text(encoding="utf-8") if gold.is_file() else ""
    agent = inputs.get("agent")
    judge_ok = False
    if agent is not None:
        prompt = (
            "Hidden reference (must not appear as a user row in observation.jsonl):\n"
            f"{gold_text}\nArtifact:\n{json.dumps(data)}\nReply with a score."
        )
        reply = asyncio.run(_invoke(agent, prompt))
        judge_ok = bool(reply.get("ok"))
    ok = data.get("ok") is True
    return {
        "status": "PASS" if ok else "FAIL",
        "score": 1.0 if ok else 0.0,
        "metrics": {"exact": 1 if ok else 0, "judge_ok": judge_ok},
        "checks": [
            evaluation_check(
                "files",
                title="artifact files",
                status="PASS" if ok else "FAIL",
                score=1.0 if ok else 0.0,
                script="evaluator.py",
            ),
            evaluation_check(
                "gold-present",
                title="gold uploaded",
                status="PASS" if gold_text else "FAIL",
                score=1.0 if gold_text else 0.0,
                script="evaluation/audit.py",
            ),
        ],
    }
