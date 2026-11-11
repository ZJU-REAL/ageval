"""Provider payload projection shared by the openai-http executor and streams.

Chat Completions and Responses keep different wire shapes; both project to the
same ``(text, thought, tool_calls)`` tuple. Streaming assembly must not invent a
third interpretation, so the executor and the stream assemblers use these
functions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def parse_tool_calls(raw: Any) -> tuple[dict[str, object], ...]:
    """Chat ``message.tool_calls`` rows to ``{id, name, arguments}`` tuples."""
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        fn = item.get("function") if isinstance(item.get("function"), Mapping) else item
        if not isinstance(fn, Mapping):
            continue
        name = str(fn.get("name") or item.get("name") or "")
        if not name:
            continue
        args: Any = fn.get("arguments") if "arguments" in fn else item.get("arguments")
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                parsed = {}
            args = parsed if isinstance(parsed, dict) else {}
        elif not isinstance(args, dict):
            args = {}
        call_id = str(item.get("id") or "")
        if not call_id:
            call_id = f"call_{len(out) + 1}"
        out.append(
            {
                "id": call_id,
                "name": name,
                "arguments": args,
            }
        )
    return tuple(out)


def chat_text_and_calls(raw: Mapping[str, Any]) -> tuple[str, str, tuple[dict[str, object], ...]]:
    """Read one Chat Completions response document."""
    message: Mapping[str, Any] = {}
    try:
        choice0 = raw["choices"][0]
        found = choice0["message"]
        if isinstance(found, Mapping):
            message = found
    except (KeyError, IndexError, TypeError):
        message = {}
    text = message.get("content") if isinstance(message.get("content"), str) else ""
    if not text and not message:
        text = json.dumps(raw)[:4000]
    thought = ""
    for key in ("reasoning_content", "reasoning"):
        raw_thought = message.get(key)
        if isinstance(raw_thought, str) and raw_thought.strip():
            thought = raw_thought
            break
    return text or "", thought, parse_tool_calls(message.get("tool_calls"))


def responses_text_and_calls(
    raw: Mapping[str, Any],
) -> tuple[str, str, tuple[dict[str, object], ...]]:
    """Read Responses ``output`` text, reasoning, and function calls."""
    texts: list[str] = []
    thoughts: list[str] = []
    calls: list[dict[str, object]] = []
    output = raw.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("type") or "")
            if kind == "reasoning":
                before = len(thoughts)
                summary = item.get("summary")
                if isinstance(summary, list):
                    for part in summary:
                        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                            thoughts.append(part["text"])
                elif isinstance(item.get("content"), str):
                    thoughts.append(item["content"])
                if len(thoughts) == before:
                    content = item.get("content")
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                                thoughts.append(part["text"])
                continue
            if kind == "function_call":
                name = str(item.get("name") or "")
                if not name:
                    continue
                args: Any = item.get("arguments")
                if isinstance(args, str):
                    try:
                        parsed = json.loads(args)
                    except json.JSONDecodeError:
                        parsed = {}
                    args = parsed if isinstance(parsed, dict) else {}
                elif not isinstance(args, dict):
                    args = {}
                call_id = (
                    str(item.get("call_id") or item.get("id") or "") or f"call_{len(calls) + 1}"
                )
                calls.append({"id": call_id, "name": name, "arguments": args})
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if part.get("type") in {"output_text", "text"} and isinstance(
                        part.get("text"), str
                    ):
                        texts.append(part["text"])
            elif isinstance(content, str):
                texts.append(content)
    if not texts and isinstance(raw.get("output_text"), str):
        texts.append(raw["output_text"])
    return "".join(texts), "\n".join(thoughts), tuple(calls)


__all__ = ["chat_text_and_calls", "parse_tool_calls", "responses_text_and_calls"]
