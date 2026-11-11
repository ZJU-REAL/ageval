"""Native SSE assembly for the openai-http executor.

Chat Completions and Responses are assembled here, never by Core or task code.
The shared transport lives in :mod:`ageval.plugins.http_stream`; this module
only knows the two OpenAI wire shapes. A Responses stream never falls back to
Chat Completions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ageval.evidence.redaction import redact_text
from ageval.plugins.contrib.openai_http.parse import responses_text_and_calls
from ageval.plugins.http_stream import (
    MAX_BUFFER,
    MAX_EVENTS,
    DeltaSink,
    StreamProtocolError,
    StreamSnapshot,
)

_SOURCE = "openai-http"
_FINISH_OK = frozenset({"stop", "tool_calls"})


def sanitize_code(value: Any) -> str:
    """Provider error code without arbitrary message text."""
    if not isinstance(value, str):
        return "unknown"
    cleaned = "".join(char for char in value if char.isalnum() or char in "._-")
    return cleaned[:64] or "unknown"


@dataclass
class _ChatTool:
    id: str = ""
    call_type: str = "function"
    name: str = ""
    arguments: str = ""


@dataclass
class _ChatChoice:
    content: list[str] = field(default_factory=list)
    thought: list[str] = field(default_factory=list)
    tools: dict[int, _ChatTool] = field(default_factory=dict)
    finish: str | None = None


class ChatAssembler:
    """Fold ``chat.completion.chunk`` frames into one Chat Completions body."""

    def __init__(self, delta_sink: DeltaSink | None = None) -> None:
        self._sink = delta_sink
        self._choices: dict[int, _ChatChoice] = {}
        self._identity: dict[str, object] = {}
        self._usage: dict[str, object] | None = None
        self._events: list[dict[str, object]] = []
        self._characters = 0
        self._error_details: dict[str, object] | None = None
        self.done = False

    def feed(self, frame: str, *, at: str) -> dict[str, int]:
        if frame == "[DONE]":
            self.done = True
            return {}
        try:
            obj = json.loads(frame)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError("stream_bad_json") from exc
        if not isinstance(obj, dict):
            raise StreamProtocolError("stream_not_object")
        if "error" in obj:
            details = _provider_error(obj, terminal="error_event")
            self._error_details = details
            raise StreamProtocolError("stream_upstream_error", details=details)
        for key in ("id", "model", "created", "system_fingerprint"):
            if key in obj:
                self._identity[key] = obj[key]
        if isinstance(obj.get("usage"), dict):
            self._usage = dict(obj["usage"])
        choices = obj.get("choices", [])
        if not isinstance(choices, list):
            raise StreamProtocolError("stream_choices_invalid")
        progress: dict[str, int] = {}
        for choice in choices:
            if not isinstance(choice, dict):
                raise StreamProtocolError("stream_choice_invalid")
            index = _choice_index(choice.get("index", 0))
            state = self._choices.setdefault(index, _ChatChoice())
            delta = choice.get("delta", {})
            if delta is None:
                delta = {}
            if not isinstance(delta, dict):
                raise StreamProtocolError("stream_delta_invalid")
            self._text_delta(state, delta, index=index, progress=progress, at=at)
            self._tool_delta(state, delta, index=index, progress=progress)
            reason = choice.get("finish_reason")
            if reason is not None:
                if not isinstance(reason, str):
                    raise StreamProtocolError("stream_finish_invalid")
                state.finish = reason
        if self._characters > MAX_BUFFER or len(self._events) > MAX_EVENTS:
            raise StreamProtocolError("stream_output_too_large")
        return progress

    def finish(self) -> dict[str, object]:
        if not self.done:
            raise StreamProtocolError("stream_missing_done")
        if 0 not in self._choices:
            raise StreamProtocolError("stream_missing_choice")
        rendered: list[dict[str, object]] = []
        for index in sorted(self._choices):
            state = self._choices[index]
            if state.finish is None:
                raise StreamProtocolError("stream_missing_finish")
            if index == 0:
                if state.finish not in _FINISH_OK:
                    self._error_details = {
                        "origin": "provider_incomplete",
                        "terminal": "chat_finish",
                        "stop_reason": sanitize_code(state.finish),
                    }
                _validate_finish(state)
            rendered.append(self._choice_document(index, state))
        raw: dict[str, object] = {
            **self._identity,
            "object": "chat.completion",
            "choices": rendered,
        }
        if self._usage is not None:
            raw["usage"] = dict(self._usage)
        return raw

    def snapshot(self) -> StreamSnapshot:
        state = self._choices.get(0)
        if state is None:
            return StreamSnapshot(status="incomplete")
        return StreamSnapshot(
            text="".join(state.content),
            thought="".join(state.thought),
            tool_calls=_partial_tool_calls(state),
            usage=dict(self._usage) if self._usage is not None else None,
            stop_reason=state.finish,
            status="incomplete",
            events=tuple(self._events),
            error_details=self._error_details,
        )

    def _text_delta(
        self,
        state: _ChatChoice,
        delta: Mapping[str, Any],
        *,
        index: int,
        progress: dict[str, int],
        at: str,
    ) -> None:
        for key, channel, target, metric in (
            ("content", "assistant", state.content, "assistant_chars"),
            ("reasoning_content", "thought", state.thought, "thought_chars"),
            ("reasoning", "thought", state.thought, "thought_chars"),
        ):
            part = delta.get(key)
            if part is None or part == "":
                continue
            if not isinstance(part, str):
                raise StreamProtocolError("stream_text_invalid")
            target.append(part)
            self._characters += len(part)
            progress[metric] = progress.get(metric, 0) + len(part)
            self._event(channel, part, at=at, index=index)

    def _tool_delta(
        self,
        state: _ChatChoice,
        delta: Mapping[str, Any],
        *,
        index: int,
        progress: dict[str, int],
    ) -> None:
        calls = delta.get("tool_calls", [])
        if calls is None:
            return
        if not isinstance(calls, list):
            raise StreamProtocolError("stream_tools_invalid")
        for call in calls:
            if not isinstance(call, Mapping):
                raise StreamProtocolError("stream_tool_invalid")
            tool_index = call.get("index")
            if isinstance(tool_index, bool) or not isinstance(tool_index, int) or tool_index < 0:
                raise StreamProtocolError("stream_tool_index_invalid")
            tool = state.tools.setdefault(tool_index, _ChatTool())
            part_id = call.get("id")
            if isinstance(part_id, str) and part_id and not tool.id:
                tool.id = part_id
            part_type = call.get("type")
            if isinstance(part_type, str) and part_type:
                tool.call_type = part_type
            fn = call.get("function")
            if fn is None:
                continue
            if not isinstance(fn, Mapping):
                raise StreamProtocolError("stream_tool_function_invalid")
            part_name = fn.get("name")
            if part_name is not None:
                if not isinstance(part_name, str):
                    raise StreamProtocolError("stream_tool_fragment_invalid")
                tool.name += part_name
            part_args = fn.get("arguments")
            if part_args is not None:
                if not isinstance(part_args, str):
                    raise StreamProtocolError("stream_tool_fragment_invalid")
                tool.arguments += part_args
                self._characters += len(part_args)
                progress["tool_chars"] = progress.get("tool_chars", 0) + len(part_args)
                if index == 0 and self._sink is not None:
                    self._sink.append(
                        "tool",
                        part_args,
                        tool_index=tool_index,
                        tool_call_id=tool.id or None,
                    )

    def _event(self, channel: str, text: str, *, at: str, index: int) -> None:
        if index != 0:
            return
        self._events.append(
            {
                "kind": "text",
                "channel": channel,
                "text": text,
                "source": _SOURCE,
                "at": at,
            }
        )
        if self._sink is not None:
            self._sink.append(channel, text)

    def _choice_document(self, index: int, state: _ChatChoice) -> dict[str, object]:
        calls = _final_tool_calls(state)
        content = "".join(state.content)
        message: dict[str, object] = {
            "role": "assistant",
            "content": content if content or not calls else None,
        }
        thought = "".join(state.thought)
        if thought:
            message["reasoning_content"] = thought
        if calls:
            message["tool_calls"] = calls
        return {"index": index, "message": message, "finish_reason": state.finish}


class _ResponseItem:
    def __init__(self, index: int, item: Mapping[str, Any]) -> None:
        self.index = index
        self.item = dict(item)
        self.content: dict[int, dict[str, object]] = {}
        self.summary: dict[int, dict[str, object]] = {}
        self.reasoning_text: dict[int, dict[str, object]] = {}
        self.arguments: list[str] = []
        self.kind = str(item.get("type") or "")
        self.item_id = str(item.get("id") or "")
        self.call_id = str(item.get("call_id") or "")
        self.name = str(item.get("name") or "")
        self._absorb(item)

    def _absorb(self, item: Mapping[str, Any]) -> None:
        kind = str(item.get("type") or self.kind)
        if kind:
            self.kind = kind
            self.item["type"] = kind
        for key in ("id", "call_id", "name", "role", "status"):
            value = item.get(key)
            if isinstance(value, str) and value:
                self.item[key] = value
                if key == "id":
                    self.item_id = value
                elif key == "call_id":
                    self.call_id = value
                elif key == "name":
                    self.name = value
        content = item.get("content")
        if isinstance(content, list):
            parts = {
                index: dict(part) for index, part in enumerate(content) if isinstance(part, Mapping)
            }
            if parts:
                self.content = parts
        summary = item.get("summary")
        if isinstance(summary, list):
            parts = {
                index: dict(part) for index, part in enumerate(summary) if isinstance(part, Mapping)
            }
            if parts:
                self.summary = parts
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            self.arguments = [arguments]


class ResponsesAssembler:
    """Fold typed Responses events into one Responses document.

    The terminal ``response.completed`` payload is authoritative when it carries
    ``output``. Delta assembly remains the fallback for gateways that omit it.
    """

    def __init__(self, delta_sink: DeltaSink | None = None) -> None:
        self._sink = delta_sink
        self._items: dict[int, _ResponseItem] = {}
        self._by_id: dict[str, int] = {}
        self._identity: dict[str, object] = {}
        self._usage: dict[str, object] | None = None
        self._events: list[dict[str, object]] = []
        self._characters = 0
        self._error_details: dict[str, object] | None = None
        self._terminal: str | None = None
        self._terminal_response: dict[str, object] | None = None
        self._terminal_reason: str | None = None
        self.done = False

    def feed(self, frame: str, *, at: str) -> dict[str, int]:
        if frame == "[DONE]":
            # Responses uses typed terminals. A bare [DONE] never completes one.
            return {}
        try:
            obj = json.loads(frame)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError("stream_bad_json") from exc
        if not isinstance(obj, dict):
            raise StreamProtocolError("stream_not_object")
        kind = obj.get("type")
        if not isinstance(kind, str) or not kind:
            raise StreamProtocolError("stream_event_type_invalid")
        if kind == "error":
            details = _provider_error(obj, terminal="error_event")
            self._error_details = details
            raise StreamProtocolError("stream_upstream_error", details=details)
        response = obj.get("response")
        if isinstance(response, dict):
            self._absorb_response(response)
        progress: dict[str, int] = {}
        if kind in {"response.created", "response.in_progress"}:
            return progress
        if kind == "response.output_item.added":
            self._output_item(obj, done=False)
            return progress
        if kind == "response.output_item.done":
            self._output_item(obj, done=True)
            return progress
        if kind in {"response.content_part.added", "response.content_part.done"}:
            self._content_part(obj, done=kind.endswith(".done"))
            return progress
        if kind == "response.output_text.delta":
            self._text_event(obj, target="content", progress=progress, at=at)
            return progress
        if kind == "response.output_text.done":
            self._text_value(obj, target="content")
            return progress
        if kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            target = "summary" if "summary" in kind else "reasoning_text"
            self._text_event(obj, target=target, progress=progress, at=at)
            return progress
        if kind in {"response.reasoning_summary_text.done", "response.reasoning_text.done"}:
            target = "summary" if "summary" in kind else "reasoning_text"
            self._text_value(obj, target=target)
            return progress
        if kind in {
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_part.done",
        }:
            self._summary_part(obj, done=kind.endswith(".done"))
            return progress
        if kind == "response.function_call_arguments.delta":
            self._function_delta(obj, progress=progress)
            return progress
        if kind == "response.function_call_arguments.done":
            self._function_done(obj)
            return progress
        if kind == "response.completed":
            self._terminal_event("completed", obj)
            return progress
        if kind == "response.incomplete":
            self._terminal_event("incomplete", obj)
            return progress
        if kind == "response.failed":
            self._terminal_event("failed", obj)
            return progress
        if kind in {"response.cancelled", "response.canceled"}:
            self._terminal_event("cancelled", obj)
            return progress
        return progress

    def finish(self) -> dict[str, object]:
        if not self.done:
            raise StreamProtocolError("stream_missing_terminal")
        if self._terminal == "failed":
            raise StreamProtocolError("stream_upstream_error")
        if self._terminal == "incomplete":
            raise StreamProtocolError(
                "stream_incomplete:" + (self._terminal_reason or "incomplete")
            )
        if self._terminal == "cancelled":
            raise StreamProtocolError("stream_cancelled")
        if self._terminal != "completed":
            raise StreamProtocolError("stream_missing_terminal")
        raw = self._completed_document()
        _validate_function_calls(raw)
        return raw

    def snapshot(self) -> StreamSnapshot:
        raw = self._document_for_snapshot()
        try:
            text, thought, calls = responses_text_and_calls(raw)
        except (TypeError, ValueError, KeyError):
            text, thought, calls = "", "", ()
        return StreamSnapshot(
            text=text,
            thought=thought,
            tool_calls=calls,
            usage=dict(self._usage) if self._usage is not None else None,
            stop_reason=self._terminal_reason or self._terminal,
            status=self._terminal,
            events=tuple(self._events),
            error_details=self._error_details,
        )

    def _absorb_response(self, response: Mapping[str, Any]) -> None:
        for key in ("id", "model", "created_at", "status"):
            if key in response:
                self._identity[key] = response[key]
        if isinstance(response.get("usage"), dict):
            self._usage = dict(response["usage"])
        output = response.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                index = _item_output_index(item, self._by_id)
                if index is None:
                    continue
                self._store_item(index, item)

    def _output_item(self, event: Mapping[str, Any], *, done: bool) -> None:
        index = self._output_index(event)
        item = event.get("item")
        if not isinstance(item, Mapping):
            raise StreamProtocolError("stream_output_item_invalid")
        self._store_item(index, item)
        if done:
            self._verify_item(index)

    def _store_item(self, index: int, item: Mapping[str, Any], *, replace: bool = False) -> None:
        current = self._items.get(index)
        if current is None or replace:
            current = _ResponseItem(index, item)
            self._items[index] = current
        else:
            current._absorb(item)
        if current.item_id:
            self._by_id[current.item_id] = index

    def _content_part(self, event: Mapping[str, Any], *, done: bool) -> None:
        index = self._output_index(event)
        part = event.get("part")
        if not isinstance(part, Mapping):
            raise StreamProtocolError("stream_content_part_invalid")
        content_index = _content_index(event)
        item = self._item(index)
        existing = item.content.get(content_index, {})
        merged = {**existing, **dict(part)}
        item.content[content_index] = merged
        del done

    def _text_event(
        self,
        event: Mapping[str, Any],
        *,
        target: str,
        progress: dict[str, int],
        at: str,
    ) -> None:
        index = self._output_index(event)
        piece = event.get("delta")
        if not isinstance(piece, str):
            raise StreamProtocolError("stream_text_invalid")
        if not piece:
            return
        item = self._item(index)
        if target != "content" and item.kind == "message":
            item.kind = "reasoning"
            item.item["type"] = "reasoning"
        content_index = _text_index(event, target)
        if target == "content":
            part = item.content.setdefault(content_index, {"type": "output_text", "text": ""})
            part["text"] = str(part.get("text") or "") + piece
            channel = "assistant"
            metric = "assistant_chars"
        elif target == "summary":
            part = item.summary.setdefault(content_index, {"type": "summary_text", "text": ""})
            part["text"] = str(part.get("text") or "") + piece
            channel = "thought"
            metric = "thought_chars"
        else:
            part = item.reasoning_text.setdefault(
                content_index, {"type": "reasoning_text", "text": ""}
            )
            part["text"] = str(part.get("text") or "") + piece
            channel = "thought"
            metric = "thought_chars"
        self._characters += len(piece)
        progress[metric] = progress.get(metric, 0) + len(piece)
        self._event(channel, piece, at=at)
        if self._sink is not None:
            self._sink.append(channel, piece)

    def _text_value(self, event: Mapping[str, Any], *, target: str) -> None:
        index = self._output_index(event)
        text = event.get("text")
        if not isinstance(text, str):
            raise StreamProtocolError("stream_text_invalid")
        item = self._item(index)
        if target != "content" and item.kind == "message":
            item.kind = "reasoning"
            item.item["type"] = "reasoning"
        content_index = _text_index(event, target)
        if target == "content":
            item.content[content_index] = {"type": "output_text", "text": text}
        elif target == "summary":
            item.summary[content_index] = {"type": "summary_text", "text": text}
        else:
            item.reasoning_text[content_index] = {"type": "reasoning_text", "text": text}

    def _summary_part(self, event: Mapping[str, Any], *, done: bool) -> None:
        index = self._output_index(event)
        part = event.get("part")
        if not isinstance(part, Mapping):
            raise StreamProtocolError("stream_content_part_invalid")
        content_index = _text_index(event, "summary")
        item = self._item(index)
        if item.kind == "message":
            item.kind = "reasoning"
            item.item["type"] = "reasoning"
        existing = item.summary.get(content_index, {})
        item.summary[content_index] = {**existing, **dict(part)}
        del done

    def _function_delta(self, event: Mapping[str, Any], *, progress: dict[str, int]) -> None:
        index = self._output_index(event)
        piece = event.get("delta")
        if not isinstance(piece, str):
            raise StreamProtocolError("stream_tool_fragment_invalid")
        if not piece:
            return
        item = self._item(index)
        if item.kind != "function_call":
            item.kind = "function_call"
            item.item["type"] = "function_call"
        item.arguments.append(piece)
        self._characters += len(piece)
        if self._characters > MAX_BUFFER:
            raise StreamProtocolError("stream_output_too_large")
        progress["tool_chars"] = progress.get("tool_chars", 0) + len(piece)
        if self._sink is not None:
            self._sink.append(
                "tool",
                piece,
                tool_index=index,
                tool_call_id=item.call_id or item.item_id or None,
            )

    def _function_done(self, event: Mapping[str, Any]) -> None:
        index = self._output_index(event)
        arguments = event.get("arguments")
        if arguments is not None and not isinstance(arguments, str):
            raise StreamProtocolError("stream_tool_fragment_invalid")
        item = self._item(index)
        if isinstance(arguments, str):
            item.arguments = [arguments]
        if isinstance(event.get("name"), str) and event["name"]:
            item.name = str(event["name"])
            item.item["name"] = item.name

    def _terminal_event(self, terminal: str, event: Mapping[str, Any]) -> None:
        response = event.get("response")
        source: Mapping[str, Any] = event
        if isinstance(response, dict):
            self._terminal_response = dict(response)
            self._absorb_response(response)
            source = response
        if terminal == "incomplete":
            details = source.get("incomplete_details")
            if isinstance(details, Mapping):
                self._terminal_reason = sanitize_code(details.get("reason"))
            if self._terminal_reason is None:
                self._terminal_reason = sanitize_code(
                    source.get("reason") or event.get("reason") or "incomplete"
                )
            self._error_details = {
                "origin": "provider_incomplete",
                "terminal": "incomplete",
                "reason": self._terminal_reason,
            }
        elif terminal == "failed":
            self._error_details = _provider_error(source, terminal="failed")
        elif terminal == "cancelled":
            self._error_details = {"origin": "cancelled", "terminal": "cancelled"}
        self._terminal = terminal
        self.done = True

    def _item(self, index: int) -> _ResponseItem:
        item = self._items.get(index)
        if item is None:
            item = _ResponseItem(index, {"type": "message", "role": "assistant"})
            self._items[index] = item
        return item

    def _output_index(self, event: Mapping[str, Any]) -> int:
        raw = event.get("output_index")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            return raw
        item_id = event.get("item_id")
        if isinstance(item_id, str) and item_id in self._by_id:
            return self._by_id[item_id]
        raise StreamProtocolError("stream_output_index_invalid")

    def _verify_item(self, index: int) -> None:
        item = self._items.get(index)
        if item is None or item.kind != "function_call":
            return
        _verified_function_call(item)

    def _event(self, channel: str, text: str, *, at: str) -> None:
        self._events.append(
            {
                "kind": "text",
                "channel": channel,
                "text": text,
                "source": _SOURCE,
                "at": at,
            }
        )
        if self._characters > MAX_BUFFER or len(self._events) > MAX_EVENTS:
            raise StreamProtocolError("stream_output_too_large")

    def _assembled_output(self) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for index in sorted(self._items):
            item = self._items[index]
            if item.kind == "message":
                parts = [
                    dict(item.content[key]) for key in sorted(item.content) if item.content[key]
                ]
                rendered = dict(item.item)
                rendered["content"] = parts
                output.append(rendered)
                continue
            if item.kind == "reasoning":
                summary = [
                    dict(item.summary[key]) for key in sorted(item.summary) if item.summary[key]
                ]
                reasoning = [
                    dict(item.reasoning_text[key])
                    for key in sorted(item.reasoning_text)
                    if item.reasoning_text[key]
                ]
                rendered = dict(item.item)
                if summary:
                    rendered["summary"] = summary
                if reasoning:
                    rendered["content"] = reasoning
                output.append(rendered)
                continue
            if item.kind == "function_call":
                arguments = "".join(item.arguments)
                rendered = dict(item.item)
                rendered.update(
                    {
                        "type": "function_call",
                        "call_id": item.call_id,
                        "name": item.name,
                        "arguments": arguments,
                    }
                )
                if item.item_id:
                    rendered["id"] = item.item_id
                output.append(rendered)
                continue
            output.append(dict(item.item))
        return output

    def _completed_document(self) -> dict[str, object]:
        response = dict(self._terminal_response) if self._terminal_response is not None else {}
        output = response.get("output")
        assembled = self._assembled_output()
        if not isinstance(output, list) or not output:
            output = assembled
        else:
            text, _thought, calls = responses_text_and_calls({"output": output})
            if not text.strip() and not calls:
                output = assembled
        raw: dict[str, object] = {
            **self._identity,
            **response,
            "object": "response",
            "status": "completed",
            "output": output,
        }
        if "output_text" not in raw:
            text = _output_text(output)
            if text:
                raw["output_text"] = text
        usage = response.get("usage")
        if not isinstance(usage, dict):
            usage = self._usage
        if isinstance(usage, dict):
            raw["usage"] = dict(usage)
        return raw

    def _document_for_snapshot(self) -> dict[str, object]:
        response = dict(self._terminal_response) if self._terminal_response is not None else {}
        output = response.get("output")
        assembled = self._assembled_output()
        if not isinstance(output, list) or not output:
            output = assembled
        else:
            text, _thought, calls = responses_text_and_calls({"output": output})
            if not text.strip() and not calls:
                output = assembled
        return {
            **self._identity,
            **response,
            "object": "response",
            "output": output,
            "status": self._terminal or "incomplete",
        }


def _bounded_redacted(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return redact_text(value)[:limit]


def _provider_error(event: Mapping[str, Any], *, terminal: str) -> dict[str, object]:
    """Provider-reported type/code/message, redacted before sealing.

    ``origin`` keeps an upstream provider error distinct from a local SSE/JSON
    parse failure even when both surface as ``ProtocolError``.
    """
    nested = event.get("error")
    sources: list[Mapping[str, Any]] = [event]
    if isinstance(nested, Mapping):
        sources.insert(0, nested)
    details: dict[str, object] = {"origin": "upstream", "terminal": terminal}
    for key, limit in (("type", 128), ("code", 128), ("param", 128), ("message", 2000)):
        for source in sources:
            value = _bounded_redacted(source.get(key), limit)
            if value is not None:
                details[key] = sanitize_code(value) if key in {"type", "code"} else value
                break
    return details


def _choice_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StreamProtocolError("stream_choice_index_invalid")
    return value


def _content_index(event: Mapping[str, Any]) -> int:
    raw = event.get("content_index", 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise StreamProtocolError("stream_content_index_invalid")
    return raw


def _text_index(event: Mapping[str, Any], target: str) -> int:
    raw = event.get("summary_index", 0) if target == "summary" else event.get("content_index", 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise StreamProtocolError("stream_content_index_invalid")
    return raw


def _item_output_index(item: Mapping[str, Any], by_id: Mapping[str, int]) -> int | None:
    raw = item.get("output_index")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id in by_id:
        return by_id[item_id]
    return None


def _event_code(event: Mapping[str, Any]) -> str:
    raw = event.get("code")
    if not isinstance(raw, str):
        error = event.get("error")
        if isinstance(error, Mapping):
            raw = error.get("code") or error.get("type")
    return sanitize_code(raw)


def _validate_finish(state: _ChatChoice) -> None:
    reason = state.finish or ""
    if reason in _FINISH_OK:
        if reason == "tool_calls" and not state.tools:
            raise StreamProtocolError("stream_missing_tool_calls")
        return
    raise StreamProtocolError("stream_incomplete:" + (sanitize_code(reason)))


def _final_tool_calls(state: _ChatChoice) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    for index in sorted(state.tools):
        tool = state.tools[index]
        if not tool.id or not tool.name:
            raise StreamProtocolError("stream_tool_identity_missing")
        arguments = tool.arguments
        if arguments:
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise StreamProtocolError("stream_tool_json_incomplete") from exc
            if not isinstance(parsed, dict):
                raise StreamProtocolError("stream_tool_json_not_object")
        calls.append(
            {
                "id": tool.id,
                "type": tool.call_type or "function",
                "function": {"name": tool.name, "arguments": arguments},
            }
        )
    return calls


def _partial_tool_calls(state: _ChatChoice) -> tuple[dict[str, object], ...]:
    calls: list[dict[str, object]] = []
    for index in sorted(state.tools):
        tool = state.tools[index]
        if not tool.id or not tool.name:
            continue
        try:
            parsed = json.loads(tool.arguments) if tool.arguments else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        calls.append({"id": tool.id, "name": tool.name, "arguments": parsed})
    return tuple(calls)


def _verified_function_call(item: _ResponseItem) -> dict[str, str]:
    if not item.name or not (item.call_id or item.item_id):
        raise StreamProtocolError("stream_tool_identity_missing")
    arguments = "".join(item.arguments)
    if arguments:
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError("stream_tool_json_incomplete") from exc
        if not isinstance(parsed, dict):
            raise StreamProtocolError("stream_tool_json_not_object")
    rendered = {
        "type": "function_call",
        "call_id": item.call_id,
        "name": item.name,
        "arguments": arguments,
    }
    if item.item_id:
        rendered["id"] = item.item_id
    item.item.update(rendered)
    return rendered


def _validate_function_calls(raw: Mapping[str, Any]) -> None:
    output = raw.get("output")
    if not isinstance(output, list):
        return
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "function_call":
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise StreamProtocolError("stream_tool_identity_missing")
        arguments = item.get("arguments")
        if arguments is None:
            arguments = ""
        if not isinstance(arguments, str):
            raise StreamProtocolError("stream_tool_fragment_invalid")
        if arguments:
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise StreamProtocolError("stream_tool_json_incomplete") from exc
            if not isinstance(parsed, dict):
                raise StreamProtocolError("stream_tool_json_not_object")


def _output_text(output: Sequence[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, Mapping)
                and part.get("type") in {"output_text", "text"}
                and isinstance(part.get("text"), str)
            ):
                parts.append(part["text"])
    return "".join(parts)


__all__ = [
    "ChatAssembler",
    "ResponsesAssembler",
    "sanitize_code",
]
