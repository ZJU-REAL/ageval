"""Host episode: model reply, parse, tmux, capture, repeat."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from terminus2_plugin.parser import ParseResult, parse_response
from terminus2_plugin.prompt import format_repair, system_prompt, user_prompt
from terminus2_plugin.tmux import TmuxSession
from terminus2_plugin.trajectory import episode_events

ModelCall = Callable[[list[dict[str, Any]]], Any]


@dataclass
class EpisodeResult:
    ok: bool
    error: str | None
    text: str
    events: tuple[dict[str, Any], ...]
    usage: dict[str, int]
    raw: dict[str, Any]
    keys_sent: bool = False
    replies: list[str] = field(default_factory=list)


def run_episode(
    *,
    instruction: str,
    session: TmuxSession,
    model: ModelCall,
    parser: str,
    step_limit: int,
    max_format_errors: int,
    timeout: float,
    session_id: str,
) -> EpisodeResult:
    """Drive one task. ``step_limit`` of 0 does not cap turns; ``timeout`` still does."""
    session.start()
    screen = session.capture()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(parser)},
        {"role": "user", "content": user_prompt(instruction, screen)},
    ]
    records: list[dict[str, Any]] = []
    replies: list[str] = []
    usage = _blank_usage()
    keys_sent = False
    format_errors = 0
    turns = 0
    deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
    final = ""
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return _finish(
                ok=False,
                error="terminus2_timeout",
                text=final,
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        if step_limit > 0 and turns >= step_limit:
            return _finish(
                ok=False,
                error="terminus2_step_limit",
                text=final,
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        reply = model(messages)
        turns += 1
        text = str(getattr(reply, "text", "") or "")
        replies.append(text)
        _merge_usage(usage, getattr(reply, "usage", None))
        parsed = parse_response(text, parser=parser)
        if parsed.error:
            format_errors += 1
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": format_repair(parsed.error, parser=parser)})
            if format_errors >= max_format_errors:
                return _finish(
                    ok=False,
                    error=f"terminus2_format:{parsed.error}",
                    text=text,
                    records=records,
                    usage=usage,
                    replies=replies,
                    keys_sent=keys_sent,
                    session_id=session_id,
                    turns=turns,
                )
            continue
        format_errors = 0
        final = parsed.analysis or final
        if _apply_commands(parsed, session=session, records=records):
            keys_sent = True
        if parsed.is_task_complete:
            return _finish(
                ok=True,
                error=None,
                text=final or "task_complete",
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        screen = session.capture()
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": user_prompt(instruction, screen)})


def _apply_commands(
    parsed: ParseResult,
    *,
    session: TmuxSession,
    records: list[dict[str, Any]],
) -> bool:
    sent = False
    for index, command in enumerate(parsed.commands):
        completed, note = session.send(command.keystrokes, command.duration)
        screen = session.capture()
        records.append(
            {
                "analysis": parsed.analysis if index == 0 else "",
                "plan": parsed.plan if index == 0 else "",
                "keystrokes": command.keystrokes,
                "duration": command.duration,
                "completed": completed,
                "note": note,
                "screen": screen,
            }
        )
        sent = True
        if not completed:
            break
    return sent


def _finish(
    *,
    ok: bool,
    error: str | None,
    text: str,
    records: list[dict[str, Any]],
    usage: dict[str, int],
    replies: list[str],
    keys_sent: bool,
    session_id: str,
    turns: int,
) -> EpisodeResult:
    return EpisodeResult(
        ok=ok,
        error=error,
        text=text,
        events=tuple(episode_events(records, session_id=session_id)),
        usage={key: value for key, value in usage.items() if value},
        raw={"turns": turns, "replies": replies, "steps": records},
        keys_sent=keys_sent,
        replies=replies,
    )


def _blank_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}


def _merge_usage(total: dict[str, int], raw: object) -> None:
    if not isinstance(raw, dict):
        return
    for key in total:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total[key] += value


__all__ = ["EpisodeResult", "run_episode"]
