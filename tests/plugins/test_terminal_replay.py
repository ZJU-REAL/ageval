"""mini-swe terminal action classification. Dispatch is covered with a real host."""

from __future__ import annotations

from miniswe_plugin.terminal_replay import classify_actions, comparable_output


def test_redacted_and_foreign_tools_are_explicit() -> None:
    document = classify_actions(
        [
            {
                "tool_call_id": "bash_1",
                "tool_name": "bash",
                "tool_kind": "execute",
                "arguments": {"command": "echo [REDACTED:secret]"},
                "timeout_sec": 30.0,
                "completed": True,
                "recorded_exit_code": 0,
                "recorded_output": "",
            },
            {
                "tool_call_id": "browser_1",
                "tool_name": "browser",
                "tool_kind": "domain",
                "arguments": {"url": "https://example.test"},
                "timeout_sec": None,
                "completed": True,
                "recorded_exit_code": 0,
                "recorded_output": "",
            },
        ]
    )
    assert document["tool_semantics_version"] == "miniswe.bash/1"
    missing = document["missing"]
    actions = document["actions"]
    assert isinstance(missing, list)
    assert isinstance(actions, list)
    assert "command_redacted" in missing
    assert "unsupported_action" in missing
    assert actions[0]["executable"] is False
    assert actions[1]["executable"] is False


def test_submit_marker_matches_recorded_submission_body() -> None:
    raw = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nshipped\n"
    assert comparable_output(raw, "", 0) == "shipped\n"
    assert comparable_output("hello\n", "", 0) == "hello\n"
