#!/usr/bin/env python3
"""Headless OpenHands SDK runner inside the Attempt environment.

The instruction is read from a file. The process writes one
``openhands.trajectory/1`` document and does not print the transcript.
The workspace is a local directory. This runner does not open a second sandbox.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TRAJECTORY_SCHEMA = "openhands.trajectory/1"
_CLIP = 8_000
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_RUN_ERRORS = (ImportError, OSError, ValueError, RuntimeError, TypeError, KeyError)


def _loopback(url: str | None) -> bool:
    if not url or not str(url).strip():
        return False
    text = str(url).strip()
    parsed = urlparse(text if "://" in text else f"http://{text}")
    return (parsed.hostname or "").lower() in _LOOPBACK


def _clip(text: str) -> str:
    return text[:_CLIP]


def _plain(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None or isinstance(value, bool | int | float):
        return ""
    if type(value).__name__ == "RedactedThinkingBlock":
        return ""
    if isinstance(value, dict):
        if value.get("type") in {"redacted_thinking", "redacted"}:
            return ""
        for key in ("thinking", "text"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found.strip()
        return ""
    if isinstance(value, list | tuple):
        parts = [_plain(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    for attr in ("thinking", "text"):
        found = getattr(value, attr, None)
        if isinstance(found, str) and found.strip():
            return found.strip()
    return ""


def _responses_reasoning(item: Any) -> str:
    """Plaintext Responses reasoning. Encrypted blobs are not copied."""
    if item is None:
        return ""
    chunks = [_plain(getattr(item, attr, None)) for attr in ("summary", "content")]
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _thought_text(event: Any) -> str:
    """Visible thinking attached to one SDK event, without the spoken reply."""
    chunks: list[str] = []

    def add(text: str) -> None:
        cleaned = text.strip()
        if cleaned and cleaned not in chunks:
            chunks.append(cleaned)

    add(_plain(getattr(event, "reasoning_content", None)))
    add(_plain(getattr(event, "thought", None)))
    add(_plain(getattr(event, "thinking_blocks", None)))
    add(_responses_reasoning(getattr(event, "responses_reasoning_item", None)))
    message = getattr(event, "llm_message", None)
    if message is not None:
        add(_plain(getattr(message, "reasoning_content", None)))
        add(_plain(getattr(message, "thinking_blocks", None)))
        add(_responses_reasoning(getattr(message, "responses_reasoning_item", None)))
    return _clip("\n\n".join(chunks))


def _message_text(event: Any) -> str:
    message = getattr(event, "llm_message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = item if isinstance(item, str) else getattr(item, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts)
    return ""


def _observation_text(event: Any) -> str:
    observation = getattr(event, "observation", None)
    if observation is None:
        return ""
    content = getattr(observation, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = item if isinstance(item, str) else getattr(item, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    text = getattr(observation, "text", None)
    if isinstance(text, str):
        return text
    return str(observation)


def _action_args(event: Any) -> dict[str, Any]:
    action = getattr(event, "action", None)
    if action is None:
        return {}
    dump = getattr(action, "model_dump", None)
    raw = dump() if callable(dump) else getattr(action, "__dict__", None)
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if key != "kind" and value is not None}


def steps_from_events(events: list[Any]) -> list[dict[str, Any]]:
    """Structured steps from SDK event objects. Names, not stdout."""
    steps: list[dict[str, Any]] = []
    last_thought: tuple[str, str] | None = None

    def push_thought(event: Any, text: str) -> None:
        nonlocal last_thought
        cleaned = text.strip()
        if not cleaned:
            return
        response_id = str(getattr(event, "llm_response_id", "") or "")
        key = (response_id, cleaned)
        if response_id and key == last_thought:
            return
        steps.append({"type": "thought", "content": cleaned})
        last_thought = key

    for event in events:
        name = type(event).__name__
        if name == "MessageEvent":
            source = str(getattr(event, "source", "") or "")
            content = _clip(_message_text(event))
            if source == "user":
                steps.append({"type": "user_message", "content": content})
            elif source == "agent":
                spoken = content.strip()
                thought = _thought_text(event)
                if thought and thought != spoken:
                    push_thought(event, thought)
                if spoken:
                    steps.append({"type": "assistant_message", "content": content})
            continue
        if name == "ActionEvent":
            push_thought(event, _thought_text(event))
            call_id = str(getattr(event, "tool_call_id", "") or "")
            tool_name = str(getattr(event, "tool_name", "") or "tool")
            steps.append(
                {
                    "type": "tool_call",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "arguments": _action_args(event),
                }
            )
            continue
        if name == "ObservationEvent":
            steps.append(
                {
                    "type": "tool_result",
                    "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                    "name": str(getattr(event, "tool_name", "") or "tool"),
                    "content": _clip(_observation_text(event)),
                }
            )
    return steps


def _usage(llm: Any) -> dict[str, Any] | None:
    metrics = getattr(llm, "metrics", None)
    token_usage = getattr(metrics, "accumulated_token_usage", None) if metrics is not None else None
    if token_usage is None:
        return None
    out: dict[str, Any] = {}
    for source, dest in (
        ("prompt_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("cache_read_tokens", "cached_tokens"),
    ):
        value = getattr(token_usage, source, None)
        if isinstance(value, int) and not isinstance(value, bool):
            out[dest] = value
    cost = getattr(metrics, "accumulated_cost", None)
    if isinstance(cost, int | float) and not isinstance(cost, bool):
        out["cost_usd"] = cost
    return out or None


def _document(
    *,
    model: str,
    ok: bool,
    text: str,
    error: str | None,
    steps: list[dict[str, Any]],
    usage: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": TRAJECTORY_SCHEMA,
        "model": model,
        "ok": ok,
        "text": text,
        "error": error,
        "steps": steps,
        "usage": usage,
    }


def _failed(model: str, error: str) -> dict[str, Any]:
    return _document(model=model, ok=False, text="", error=error, steps=[], usage=None)


def _step_log() -> Path:
    root = os.environ.get("AGEVAL_STATE_DIR") or "/tmp/.ageval-state"
    return Path(root) / "steps.jsonl"


def _emit_step(row: dict[str, Any]) -> None:
    path = _step_log()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return


def _emit_openhands(event: Any) -> None:
    name = type(event).__name__
    if name == "MessageEvent" and str(getattr(event, "source", "") or "") == "agent":
        text = _message_text(event).strip()
        if text:
            _emit_step({"type": "assistant", "content": text})
        return
    if name == "ActionEvent":
        _emit_step(
            {
                "type": "tool_call",
                "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                "name": str(getattr(event, "tool_name", "") or "tool"),
                "tool_kind": "other",
                "arguments": _action_args(event),
            }
        )
        return
    if name == "ObservationEvent":
        _emit_step(
            {
                "type": "tool_result",
                "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                "name": str(getattr(event, "tool_name", "") or "tool"),
                "outcome": "ok",
                "content": _observation_text(event),
            }
        )


def run_agent(instruction: str, *, workdir: str) -> dict[str, Any]:
    """One headless SDK conversation on a local workspace."""
    from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace
    from openhands.sdk.conversation import get_agent_final_response
    from openhands.tools.preset.default import get_default_tools

    model = os.environ.get("OH_MODEL", "").strip()
    if not model:
        return _failed("", "openhands_model_missing")
    base = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL") or "").strip()
    key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
    if not key:
        if _loopback(base or None):
            key = "unused"
        else:
            return _failed(model, "openhands_api_key_missing")
    llm_kwargs: dict[str, Any] = {"model": model, "api_key": key}
    if base:
        llm_kwargs["base_url"] = base
    effort = os.environ.get("OH_REASONING_EFFORT", "").strip()
    if effort:
        llm_kwargs["reasoning_effort"] = effort
    timeout_raw = os.environ.get("OH_TIMEOUT", "").strip()
    if timeout_raw:
        llm_kwargs["timeout"] = int(timeout_raw)
    llm = LLM(**llm_kwargs)
    agent = Agent(
        llm=llm,
        tools=get_default_tools(enable_browser=False),
        system_prompt_kwargs={"cli_mode": True},
    )
    # LocalWorkspace runs tools in this process. A remote workspace would
    # start another sandbox; this runner never builds one.
    workspace = LocalWorkspace(working_dir=workdir)
    max_iterations = int(os.environ.get("OH_MAX_ITERATIONS") or "40")
    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        max_iteration_per_run=max_iterations,
        visualizer=None,
    )
    import threading
    import time

    stop = threading.Event()
    seen = {"n": 0}

    def _pump() -> None:
        while not stop.is_set():
            current = list(getattr(conversation.state, "events", ()) or ())
            for event in current[seen["n"] :]:
                _emit_openhands(event)
            seen["n"] = len(current)
            time.sleep(0.05)

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    try:
        conversation.send_message(instruction)
        conversation.run()
    finally:
        stop.set()
        pump.join(timeout=1)
        current = list(getattr(conversation.state, "events", ()) or ())
        for event in current[seen["n"] :]:
            _emit_openhands(event)
    events = list(getattr(conversation.state, "events", ()) or ())
    text = str(get_agent_final_response(events) or "")
    return _document(
        model=model,
        ok=True,
        text=text,
        error=None,
        steps=steps_from_events(events),
        usage=_usage(llm),
    )


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OpenHands SDK on one instruction file")
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args(argv)
    model = os.environ.get("OH_MODEL", "").strip()
    trajectory = Path(args.trajectory)
    try:
        instruction = Path(args.instruction_file).read_text(encoding="utf-8")
        document = run_agent(instruction, workdir=str(args.workdir))
    except _RUN_ERRORS as exc:
        detail = f"{type(exc).__name__}: {exc}"
        document = _failed(model, detail[:500])
    _write(trajectory, document)
    return 0 if document.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
