"""Sum an entry-declared session journal when ACP sent no first-class usage.

The entry names the HOME-relative directory, which JSONL records count, and
how source fields map onto ageval usage. This module does not name a vendor
or a path of its own.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.evidence.usage import sealed_extra, sealed_usage


@dataclass(frozen=True, slots=True)
class UsageJournalRecord:
    type: str
    usage: str
    match: tuple[tuple[str, str], ...] = ()

    def digest_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "usage": self.usage}
        if self.match:
            out["match"] = {key: value for key, value in self.match}
        return out


@dataclass(frozen=True, slots=True)
class UsageJournal:
    dir: str
    suffix: str
    records: tuple[UsageJournalRecord, ...]
    fields: tuple[tuple[str, str], ...]
    extra: tuple[tuple[str, str], ...]

    def digest_payload(self) -> dict[str, Any]:
        return {
            "dir": self.dir,
            "suffix": self.suffix,
            "records": [record.digest_payload() for record in self.records],
            "fields": {key: value for key, value in self.fields},
            "extra": {key: value for key, value in self.extra},
        }


def _dig(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _matches(row: Mapping[str, Any], record: UsageJournalRecord) -> bool:
    if row.get("type") != record.type:
        return False
    return all(_dig(row, key) == expected for key, expected in record.match)


def _number(value: Any, *, integral: bool) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if integral:
        if isinstance(value, float) and value != int(value):
            return None
        return int(value)
    return value


def sum_journal_text(
    text: str, journal: UsageJournal
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Sum one JSONL document. A bad line is skipped. No records → ``(None, None)``."""
    totals: dict[str, int | float] = {}
    seen = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        for record in journal.records:
            if not _matches(row, record):
                continue
            bag = _dig(row, record.usage)
            if not isinstance(bag, Mapping):
                continue
            seen = True
            for target, source in (*journal.fields, *journal.extra):
                number = _number(_dig(bag, source), integral=target != "cost_usd")
                if number is None:
                    continue
                totals[target] = totals.get(target, 0) + number
    if not seen:
        return None, None
    extra: dict[str, Any] = {key: totals[key] for key, _source in journal.extra if key in totals}
    extra["sources"] = {
        "prompt_usage": False,
        "usage_update": False,
        "session_journal": True,
    }
    return (
        sealed_usage(
            prompt_tokens=_as_int(totals.get("prompt_tokens")),
            completion_tokens=_as_int(totals.get("completion_tokens")),
            cached_tokens=_as_int(totals.get("cached_tokens")),
            cost_usd=totals.get("cost_usd") if "cost_usd" in totals else None,
        ),
        sealed_extra(extra),
    )


def _as_int(value: int | float | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def sum_journal_files(
    texts: list[str], journal: UsageJournal
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Sum every document. Empty input stays omitted."""
    merged_usage: dict[str, Any] = {}
    merged_extra: dict[str, Any] = {}
    found = False
    for text in texts:
        usage, extra = sum_journal_text(text, journal)
        if usage is None and extra is None:
            continue
        found = True
        for key, value in (usage or {}).items():
            merged_usage[key] = merged_usage.get(key, 0) + value
        for key, value in (extra or {}).items():
            if key == "sources":
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged_extra[key] = merged_extra.get(key, 0) + value
    if not found:
        return None, None
    merged_extra["sources"] = {
        "prompt_usage": False,
        "usage_update": False,
        "session_journal": True,
    }
    usage_out = sealed_usage(
        prompt_tokens=_as_int(merged_usage.get("prompt_tokens")),
        completion_tokens=_as_int(merged_usage.get("completion_tokens")),
        cached_tokens=_as_int(merged_usage.get("cached_tokens")),
        cost_usd=merged_usage.get("cost_usd"),
    )
    return usage_out, sealed_extra(merged_extra)


def journal_texts(root: Path, suffix: str) -> list[str]:
    """Read journal files under *root*. A missing directory is an empty list."""
    if not root.is_dir():
        return []
    base = root.resolve()
    texts: list[str] = []
    for path in sorted(root.rglob(f"*{suffix}")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            continue
        texts.append(resolved.read_text(encoding="utf-8"))
    return texts


def journal_box_dir(home: str, journal: UsageJournal) -> str:
    return f"{home.rstrip('/')}/{journal.dir}"
