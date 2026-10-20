"""JSON and XML command batches for the terminus-2 host loop.

The shapes match the Terminus 2 plain formats: an object with analysis, plan,
and commands, or the same fields as XML. This parser does not import Harbor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```(?:json|xml)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_DURATION_CAP = 60.0
_XML_ANALYSIS = re.compile(r"<analysis>(.*?)</analysis>", re.DOTALL | re.IGNORECASE)
_XML_PLAN = re.compile(r"<plan>(.*?)</plan>", re.DOTALL | re.IGNORECASE)
_XML_COMMANDS = re.compile(r"<commands>(.*?)</commands>", re.DOTALL | re.IGNORECASE)
_XML_KEYS = re.compile(
    r"<keystrokes\b([^>]*)>(.*?)</keystrokes>",
    re.DOTALL | re.IGNORECASE,
)
_XML_DURATION = re.compile(r"""duration\s*=\s*["']([0-9]+(?:\.[0-9]+)?)["']""", re.IGNORECASE)
_XML_DONE = re.compile(r"<task_complete\b[^>]*>(.*?)</task_complete>", re.DOTALL | re.IGNORECASE)
_XML_DONE_EMPTY = re.compile(r"<task_complete\s*/>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    keystrokes: str
    duration: float


@dataclass(frozen=True, slots=True)
class ParseResult:
    commands: tuple[ParsedCommand, ...]
    is_task_complete: bool
    error: str
    warning: str
    analysis: str
    plan: str


def parse_response(text: str, *, parser: str = "json") -> ParseResult:
    """Parse one model reply. ``parser`` is ``json`` or ``xml``."""
    name = (parser or "json").strip().lower()
    if name == "xml":
        return _parse_xml(text)
    if name == "json":
        return _parse_json(text)
    return _fail(f"unknown_parser:{name}")


def _ok(
    commands: list[ParsedCommand],
    *,
    done: bool,
    analysis: str,
    plan: str,
    warning: str = "",
) -> ParseResult:
    return ParseResult(
        commands=tuple(commands),
        is_task_complete=done,
        error="",
        warning=warning,
        analysis=analysis,
        plan=plan,
    )


def _fail(error: str, *, warning: str = "", analysis: str = "", plan: str = "") -> ParseResult:
    return ParseResult(
        commands=(),
        is_task_complete=False,
        error=error,
        warning=warning,
        analysis=analysis,
        plan=plan,
    )


def _parse_json(text: str) -> ParseResult:
    raw, warning = _json_slice(text)
    if not raw:
        return _fail("no_json", warning=warning)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail(f"invalid_json:{exc.msg}", warning=warning)
    if not isinstance(data, dict):
        return _fail("json_not_object", warning=warning)
    missing = [name for name in ("analysis", "plan", "commands") if name not in data]
    if missing:
        return _fail("missing_fields:" + ",".join(missing), warning=warning)
    analysis = data.get("analysis")
    plan = data.get("plan")
    if not isinstance(analysis, str) or not isinstance(plan, str):
        return _fail("analysis_plan_not_string", warning=warning)
    commands, error = _commands_from(data.get("commands"))
    done = _as_bool(data.get("task_complete", False))
    if error:
        if done:
            return _ok([], done=True, analysis=analysis, plan=plan, warning=_join(warning, error))
        return _fail(error, warning=warning, analysis=analysis, plan=plan)
    return _ok(commands, done=done, analysis=analysis, plan=plan, warning=warning)


def _parse_xml(text: str) -> ParseResult:
    body = text or ""
    analysis_m = _XML_ANALYSIS.search(body)
    plan_m = _XML_PLAN.search(body)
    commands_m = _XML_COMMANDS.search(body)
    if analysis_m is None or plan_m is None or commands_m is None:
        return _fail("missing_xml_sections")
    analysis = analysis_m.group(1).strip()
    plan = plan_m.group(1).strip()
    commands: list[ParsedCommand] = []
    for attrs, payload in _XML_KEYS.findall(commands_m.group(1)):
        duration = _duration_attr(attrs)
        if duration is None:
            return _fail("bad_duration", analysis=analysis, plan=plan)
        commands.append(ParsedCommand(keystrokes=payload, duration=duration))
    done = False
    done_m = _XML_DONE.search(body)
    if done_m is not None:
        done = _as_bool(done_m.group(1).strip())
    elif _XML_DONE_EMPTY.search(body):
        done = False
    return _ok(commands, done=done, analysis=analysis, plan=plan)


def _commands_from(raw: object) -> tuple[list[ParsedCommand], str]:
    if not isinstance(raw, list):
        return [], "commands_not_list"
    out: list[ParsedCommand] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"command_not_object:{index}"
        keys = item.get("keystrokes")
        if not isinstance(keys, str):
            return [], f"keystrokes_missing:{index}"
        if "duration" not in item or item.get("duration") in (None, ""):
            duration = 1.0
        else:
            duration = _duration_value(item.get("duration"))
            if duration is None:
                return [], f"bad_duration:{index}"
        out.append(ParsedCommand(keystrokes=keys, duration=duration))
    return out, ""


def _duration_attr(attrs: str) -> float | None:
    match = _XML_DURATION.search(attrs or "")
    if match is None:
        return 1.0
    return _duration_value(match.group(1))


def _duration_value(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return min(value, _DURATION_CAP)


def _as_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return False


def _json_slice(text: str) -> tuple[str, str]:
    body = text or ""
    warning = ""
    fenced = _FENCE.findall(body)
    if fenced:
        body = fenced[0]
        warning = "fenced"
    start = _object_start(body)
    if start < 0:
        return "", warning
    end = _object_end(body, start)
    if end < 0:
        return "", warning
    if body[:start].strip() or body[end + 1 :].strip():
        warning = _join(warning, "extra_text")
    return body[start : end + 1], warning


def _object_start(text: str) -> int:
    return text.find("{")


def _object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _join(left: str, right: str) -> str:
    parts = [part for part in (left, right) if part]
    return "; ".join(parts)


__all__ = ["ParseResult", "ParsedCommand", "parse_response"]
