"""Coordinator plus six child sessions inside one Attempt.

Each child has its own session and a search/answer loop. At most four run
at once. The parent ceiling is limits.agent_concurrency; this gather limit
cannot raise it. One child failure stays in its slot.
"""

from __future__ import annotations

import json
from typing import Any

from ageval_sdk import RunContext, RunTerminal, bounded_gather

_SEARCH = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Look up one topic in the local corpus.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def _corpus(ctx: RunContext) -> dict[str, str]:
    raw = json.loads((ctx.workspace_root / "corpus.json").read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in raw.items()}


def _lookup(corpus: dict[str, str], arguments: dict[str, Any], topic: str) -> str:
    query = str(arguments.get("query") or topic).strip().lower()
    return corpus.get(query, "")


async def _child(ctx: RunContext, topic: str, corpus: dict[str, str]) -> dict[str, Any]:
    prompt = (
        f"Topic: {topic}. Call the search tool with query {topic!r}. "
        "After the tool returns, reply with only that sentence."
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    text = ""
    fact = ""
    async with ctx.agent.session("solver", max_turns=4) as session:
        for _ in range(3):
            reply = await session.invoke(prompt, tools=_SEARCH, messages=messages)
            if not reply.get("ok"):
                return {
                    "topic": topic,
                    "ok": False,
                    "error": reply.get("error"),
                    "text": text,
                    "fact": fact,
                }
            text = str(reply.get("text") or "")
            calls = list(reply.get("tool_calls") or [])
            if not calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call.get("arguments") or {}),
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                found = _lookup(corpus, arguments, topic)
                if found:
                    fact = found
                await session.record_observation(
                    str(call.get("id") or ""),
                    content=found,
                    function_name=str(call.get("name") or "search"),
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or ""),
                        "content": found,
                    }
                )
    return {"topic": topic, "ok": True, "error": None, "text": text, "fact": fact}


async def run(ctx: RunContext) -> RunTerminal:
    corpus = _corpus(ctx)
    topics = [str(topic) for topic in ctx.params["topics"]]
    children = await bounded_gather(
        [_child(ctx, topic, corpus) for topic in topics],
        limit=4,
    )
    notes = []
    for topic, child in zip(topics, children, strict=True):
        if isinstance(child, BaseException):
            notes.append({"topic": topic, "ok": False, "error": type(child).__name__, "text": ""})
        else:
            notes.append(child)
    lines = "\n".join(
        f"{note['topic']}: {note.get('text') or note.get('error') or ''}" for note in notes
    )
    async with ctx.agent.session("solver", max_turns=2) as coordinator:
        synthesis = await coordinator.invoke(
            "Write one JSON object mapping each topic to its sentence. "
            "Use the notes as written.\n" + lines
        )
    ctx.publish_json(
        "report",
        {
            "children": notes,
            "synthesis": str(synthesis.get("text") or ""),
            "synthesis_ok": bool(synthesis.get("ok")),
        },
    )
    failed = [note["topic"] for note in notes if not note.get("ok")]
    if failed or not synthesis.get("ok"):
        return RunTerminal.failed("child_or_synthesis_failed")
    return RunTerminal.completed("gathered")
