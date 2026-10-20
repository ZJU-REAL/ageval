"""Instructions for one terminus-2 episode. The schema is the parser's schema."""

from __future__ import annotations

_JSON = """\
You are solving a task in a Linux tmux pane.
Reply with one JSON object and no other text.

{
  "analysis": "what the pane shows",
  "plan": "the next commands",
  "commands": [{"keystrokes": "ls\\n", "duration": 0.1}],
  "task_complete": false
}

Rules:
- analysis, plan, and commands are required. task_complete defaults to false.
- keystrokes are sent to tmux verbatim. End a command with a newline or it will not run.
- duration is seconds to wait (default 1, maximum 60). Use C-c for Ctrl+C.
- Set task_complete to true only after the task is done. You may still include the last commands.
"""

_XML = """\
You are solving a task in a Linux tmux pane.
Reply with one XML document and no other text.

<response>
<analysis>what the pane shows</analysis>
<plan>the next commands</plan>
<commands>
<keystrokes duration="0.1">ls
</keystrokes>
</commands>
<task_complete>false</task_complete>
</response>

Rules:
- analysis, plan, and commands are required.
- keystrokes are sent to tmux verbatim, including the trailing newline.
- duration is seconds to wait (default 1, maximum 60).
- Set task_complete to true only after the task is done.
"""


def system_prompt(parser: str) -> str:
    if parser == "xml":
        return _XML
    return _JSON


def user_prompt(instruction: str, screen: str) -> str:
    shown = screen if screen.strip() else "(empty pane)"
    return f"Task:\n{instruction.strip()}\n\nCurrent terminal:\n{shown}\n"


def format_repair(error: str, *, parser: str) -> str:
    kind = "XML document" if parser == "xml" else "JSON object"
    return f"Could not parse that reply ({error}). Send one {kind} only."


__all__ = ["format_repair", "system_prompt", "user_prompt"]
