"""Terminus-2 JSON and XML command parsers. No model and no environment."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "terminus-2" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from terminus2_plugin.parser import parse_response  # noqa: E402


def test_json_batch_and_completion() -> None:
    raw = """
    note
    {
      "analysis": "empty dir",
      "plan": "write the file",
      "commands": [{"keystrokes": "printf 'hello\\\\n' > hello.txt\\n", "duration": 0.1}],
      "task_complete": false
    }
    trailing
    """
    parsed = parse_response(raw, parser="json")
    assert parsed.error == ""
    assert parsed.analysis == "empty dir"
    assert parsed.is_task_complete is False
    assert parsed.commands[0].keystrokes == "printf 'hello\\n' > hello.txt\n"
    assert parsed.commands[0].duration == 0.1
    assert "extra_text" in parsed.warning


def test_json_fence_and_default_duration() -> None:
    raw = """```json
{"analysis": "a", "plan": "p", "commands": [{"keystrokes": "ls\\n"}]}
```"""
    parsed = parse_response(raw)
    assert parsed.error == ""
    assert parsed.commands[0].duration == 1.0
    assert parsed.commands[0].keystrokes == "ls\n"
    assert "fenced" in parsed.warning


def test_json_complete_ignores_bad_commands() -> None:
    raw = '{"analysis": "done", "plan": "stop", "commands": "nope", "task_complete": true}'
    parsed = parse_response(raw)
    assert parsed.error == ""
    assert parsed.is_task_complete is True
    assert parsed.commands == ()


def test_json_rejects_missing_fields() -> None:
    parsed = parse_response('{"analysis": "a", "commands": []}')
    assert parsed.error.startswith("missing_fields:")
    assert parsed.commands == ()


def test_xml_keystrokes_keep_newlines() -> None:
    raw = """<response>
<analysis>see prompt</analysis>
<plan>list</plan>
<commands>
<keystrokes duration="0.2">ls -la
</keystrokes>
</commands>
<task_complete>false</task_complete>
</response>"""
    parsed = parse_response(raw, parser="xml")
    assert parsed.error == ""
    assert parsed.commands[0].duration == 0.2
    assert parsed.commands[0].keystrokes.endswith("\n")
    assert parsed.is_task_complete is False


def test_xml_task_complete() -> None:
    raw = """<analysis>wrote it</analysis><plan>stop</plan>
<commands></commands><task_complete>true</task_complete>"""
    parsed = parse_response(raw, parser="xml")
    assert parsed.error == ""
    assert parsed.is_task_complete is True
    assert parsed.commands == ()


def test_duration_caps_at_sixty() -> None:
    raw = '{"analysis": "a", "plan": "p", "commands": [{"keystrokes": "", "duration": 120}]}'
    parsed = parse_response(raw)
    assert parsed.error == ""
    assert parsed.commands[0].duration == 60.0
