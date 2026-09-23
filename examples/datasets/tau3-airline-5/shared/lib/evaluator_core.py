"""Independent evaluator: replay tau2 ENV+COMMUNICATE scoring."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Any

from shared.lib.bridge import load_eval_task, make_environment


def _rebuild_messages(raw: list[dict[str, Any]]) -> list[Any]:
    from tau2.data_model.message import (
        AssistantMessage,
        ToolMessage,
        UserMessage,
    )

    out: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role == "user":
            out.append(UserMessage.model_validate(item))
        elif role == "assistant":
            out.append(AssistantMessage.model_validate(item))
        elif role == "tool":
            out.append(ToolMessage.model_validate(item))
        elif item.get("tool_calls") is not None:
            out.append(AssistantMessage.model_validate(item))
        else:
            try:
                out.append(AssistantMessage.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
    return out


def evaluate(
    inputs: dict[str, Any],
    *,
    task_dir: Path,
    upstream_task_id: str,
) -> dict[str, Any]:
    sim_path = Path(inputs["artifacts"]["simulation"])
    sim = json.loads(sim_path.read_text(encoding="utf-8"))
    messages_raw = sim.get("messages") if isinstance(sim.get("messages"), list) else []
    messages = _rebuild_messages(messages_raw)

    task = load_eval_task(upstream_task_id, task_dir / "evaluation" / "task.json")

    from datetime import datetime

    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.registry import registry

    term_raw = str(sim.get("termination_reason") or "user_stop")
    try:
        term = TerminationReason(term_raw)
    except Exception:  # noqa: BLE001
        mapping = {
            "USER_STOP": TerminationReason.USER_STOP,
            "AGENT_STOP": TerminationReason.AGENT_STOP,
            "user_stop": TerminationReason.USER_STOP,
            "agent_stop": TerminationReason.AGENT_STOP,
            "max_steps": TerminationReason.MAX_STEPS,
        }
        term = mapping.get(term_raw, TerminationReason.USER_STOP)

    now = datetime.now(UTC).isoformat()
    simulation = SimulationRun(
        id=f"ageval-{upstream_task_id}",
        task_id=str(upstream_task_id),
        start_time=now,
        end_time=now,
        duration=0.0,
        messages=messages,
        termination_reason=term,
    )

    def env_ctor(**kwargs):  # noqa: ANN003
        return make_environment()

    try:
        registry._domains["airline"] = env_ctor  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass

    reward_info = evaluate_simulation(
        simulation=simulation,
        task=task,
        evaluation_type=EvaluationType.ALL,
        solo_mode=False,
        domain="airline",
    )
    reward = float(reward_info.reward) if reward_info.reward is not None else 0.0
    breakdown = None
    if reward_info.reward_breakdown:
        breakdown = {str(k): float(v) for k, v in reward_info.reward_breakdown.items()}
    info = reward_info.info if isinstance(reward_info.info, dict) else {}
    db_match = None
    if reward_info.db_check is not None:
        db_match = bool(reward_info.db_check.db_match)
    ok = reward >= 1.0
    return {
        "status": "PASS" if ok else "FAIL",
        "score": reward,
        "metrics": {
            "reward": reward,
            "reward_breakdown": breakdown,
            "db_match": db_match,
            "termination_reason": term_raw,
            "n_messages": len(messages),
            "note": info.get("note") if isinstance(info, dict) else None,
        },
    }
