"""Log mini-swe steps and replay completed ones without another model or bash call."""

from __future__ import annotations

from typing import Any

from ageval.plugins.step_activity import (
    StepReplay,
    checkpoint_prepare,
    next_step,
    scope_of,
)

_TOOLS = frozenset({"bash"})


def install_activity(model: Any, env: Any, executor: Any) -> None:
    scope = scope_of(executor)
    if scope is None:
        return
    replay = StepReplay(scope, tool_names=_TOOLS)
    orig_query = model.query

    def query(messages: Any, **kwargs: Any) -> Any:
        cached = replay.take_model()
        if cached is not None:
            usage = (
                cached.payload.get("usage") if isinstance(cached.payload.get("usage"), dict) else {}
            )
            inherited = cached.payload.get("inherited") is True
            cost = 0.0 if inherited else usage.get("cost_usd") if isinstance(usage, dict) else 0.0
            return {
                "role": "assistant",
                "content": cached.payload.get("assistant_text") or "",
                "extra": {
                    "actions": list(cached.payload.get("tool_calls") or []),
                    "cost": 0.0 if inherited else (cost or 0.0),
                    "inherited": inherited,
                },
            }
        step = next_step(scope)
        tail = _tail(messages)
        scope.record_model_turn_in_flight(step, tail)
        try:
            message = orig_query(messages, **kwargs)
        except Exception:  # noqa: BLE001 — a cut-off model turn stays in the log
            scope.record_model_turn_aborted(step, reason="process_interrupted")
            raise
        actions: list[Any] = []
        extra = message.get("extra") if isinstance(message, dict) else None
        if isinstance(extra, dict) and isinstance(extra.get("actions"), list):
            actions = list(extra["actions"])
        content = message.get("content") if isinstance(message, dict) else ""
        scope.record_model_turn_completed(
            step,
            assistant_text=str(content or ""),
            tool_calls=actions,
            usage=_usage(extra),
        )
        return message

    model.query = query
    orig_exec = env.execute
    counter = {"n": _bash_ordinal(scope)}

    def execute(action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        cached = replay.take_tool()
        if cached is not None:
            code = cached.payload.get("exit_code")
            out = {
                "output": str(cached.payload.get("content") or ""),
                "returncode": code if isinstance(code, int) and not isinstance(code, bool) else 0,
                "exception_info": "",
            }
            from miniswe_plugin.env import _check_submitted

            _check_submitted(out)
            return out
        counter["n"] += 1
        call_id = f"bash_{counter['n']}"
        command = str(action.get("command") or "")
        from ageval.evidence.system_effect import command_system_effect

        scope.record_tool_call_in_flight(
            call_id,
            "bash",
            "execute",
            {"command": command},
            replay_safe=False,
            system_effect=command_system_effect(command, cwd or None),
            timeout_sec=float(timeout or getattr(env, "timeout", 30)),
        )
        env._exec_request_id = f"tool_{scope.session_id}_{call_id}"
        try:
            out = orig_exec(action, cwd, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — Submitted exits; other errors stay in the log
            content = _submitted_content(exc)
            scope.record_tool_call_completed(
                call_id,
                outcome="ok" if content is not None else "error",
                exit_code=0 if content is not None else None,
                content=content if content is not None else f"{type(exc).__name__}:{exc}",
                prepare=checkpoint_prepare(scope),
            )
            raise
        finally:
            env._exec_request_id = None
        code = int(out.get("returncode") or 0)
        scope.record_tool_call_completed(
            call_id,
            outcome="ok" if code == 0 else "error",
            exit_code=code,
            content=str(out.get("output") or ""),
            prepare=checkpoint_prepare(scope),
        )
        return out

    env.execute = execute


def _bash_ordinal(scope: Any) -> int:
    """Highest ``bash_N`` already stored for this session. New tools start after it."""
    prefix = f"tool_{scope.session_id}_bash_"
    best = 0
    for record in scope.log.records:
        if record.kind != "tool_call" or not str(record.request_id).startswith(prefix):
            continue
        suffix = str(record.request_id)[len(prefix) :]
        if suffix.isdigit():
            best = max(best, int(suffix))
    return best


def _tail(messages: Any) -> list[dict[str, Any]]:
    """Tool results that followed the latest assistant message.

    One model reply can run several bash actions. Keeping only ``messages[-1]``
    drops every result except the last.
    """
    if not isinstance(messages, list) or not messages:
        return []
    start = len(messages)
    saw_assistant = False
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if isinstance(item, dict) and item.get("role") == "assistant":
            start = index + 1
            saw_assistant = True
            break
    if not saw_assistant:
        last = messages[-1]
        return [dict(last)] if isinstance(last, dict) else []
    return [dict(item) for item in messages[start:] if isinstance(item, dict)]


def _usage(extra: Any) -> dict[str, Any] | None:
    if not isinstance(extra, dict):
        return None
    cost = extra.get("cost")
    if isinstance(cost, int | float) and not isinstance(cost, bool):
        return {"cost_usd": float(cost)}
    return None


def _submitted_content(exc: BaseException) -> str | None:
    try:
        from minisweagent.exceptions import Submitted
    except ImportError:
        return None
    if not isinstance(exc, Submitted):
        return None
    payload = exc.args[0] if exc.args else None
    if isinstance(payload, dict):
        return str(payload.get("content") or "")
    return ""
