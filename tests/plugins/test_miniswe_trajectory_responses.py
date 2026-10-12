"""Responses-API shaped miniswe messages map into ageval trajectory events."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.trajectory import to_ageval_trajectory_events  # noqa: E402


def test_responses_function_call_and_output_map_to_tool_events() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {
            "object": "response",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_abc",
                    "name": "bash",
                    "arguments": '{"command": "echo turn1"}',
                }
            ],
            "extra": {
                "actions": [{"command": "echo turn1", "tool_call_id": "call_abc"}],
                "cost": 0.0,
            },
        },
        {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": "turn1\n",
            "extra": {"returncode": 0, "raw_output": "turn1\n"},
        },
        {
            "object": "response",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_def",
                    "name": "bash",
                    "arguments": '{"command": "echo turn2"}',
                }
            ],
            "extra": {
                "actions": [{"command": "echo turn2", "tool_call_id": "call_def"}],
                "cost": 0.0,
            },
        },
    ]
    events = to_ageval_trajectory_events(messages, session_id="s")
    kinds = [(e.get("kind"), e.get("phase") or e.get("channel")) for e in events]
    assert ("text", "system") in kinds
    assert ("text", "user") in kinds
    starts = [e for e in events if e.get("kind") == "tool" and e.get("phase") == "start"]
    updates = [e for e in events if e.get("kind") == "tool" and e.get("phase") == "update"]
    assert len(starts) == 2
    assert starts[0]["args"]["command"] == "echo turn1"
    assert starts[1]["args"]["command"] == "echo turn2"
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "call_abc"
    assert updates[0]["status"] == "completed"
