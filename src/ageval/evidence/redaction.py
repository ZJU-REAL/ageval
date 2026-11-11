"""Redaction and fail-closed secret scan for trajectory evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any

# Patterns that indicate secrets / credentials in serialized evidence.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*:\s*)bearer\s+\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|credential)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)(xox[baprs]-)[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+@"),
    re.compile(r"(?i)(mysql://[^:\s/]+:)[^@\s]+@"),
    re.compile(r"(?i)(mongodb(?:\+srv)?://[^:\s/]+:)[^@\s]+@"),
    re.compile(r"(?i)cookie\s*[:=]\s*[^\s;]+"),
    # Host credential path shapes that must not appear in evidence.
    re.compile(r"(?i)/Users/[^/\s]+/\.codex/auth\.json"),
    re.compile(r"(?i)/home/[^/\s]+/\.codex/auth\.json"),
    re.compile(r"(?i)~/?\.codex/auth\.json"),
)

_REDACTED = "[REDACTED:secret]"

# Keep credential introductions with the unfinished value that follows them.
# The final non-whitespace token is retained separately, including URL/path
# credentials and a secret whose prefix has not reached its minimum length yet.
_STREAM_CONTEXT = re.compile(
    r"(?i)(?:authorization\s*:?\s*|authorization\s*:\s*"
    r"(?:[a-z]*|bearer\s+\S*)|bearer(?:\s+[A-Za-z0-9\-._~+/=]*)?|"
    r"(?:api[_-]?key|secret|token|password|passwd|credential|cookie)"
    r"\s*(?:[:=]\s*\S*)?)$"
)


class RedactionError(Exception):
    """Raised when residual secret content is found after redaction (fail closed)."""

    def __init__(self, message: str, *, hits: list[str] | None = None) -> None:
        super().__init__(message)
        # Never include the secret values themselves — only class labels.
        self.hits = list(hits or [])


def redact_text(text: str, *, extra_sentinels: Iterable[str] = ()) -> str:
    """Replace known secret shapes and explicit sentinels in a string."""
    out = text
    for s in extra_sentinels:
        if s and s in out:
            out = out.replace(s, _REDACTED)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_REDACTED, out)
    return out


class IncrementalTextRedactor:
    """Release redacted text only after its credential context is complete.

    A socket read, flush timer, or output chunk boundary is not a redaction
    boundary. Retain the unfinished token, credential introduction, and any
    explicit sentinel prefix until more text or the terminal flush arrives.
    """

    def __init__(self, *, extra_sentinels: Iterable[str] = ()) -> None:
        self._sentinels = tuple(s for s in extra_sentinels if s)
        self._pending = ""

    def feed(self, text: str, *, final: bool = False) -> str:
        self._pending += text
        if final:
            value, self._pending = self._pending, ""
            return redact_text(value, extra_sentinels=self._sentinels)
        boundary = re.search(r"\s+(?=\S*$)", self._pending)
        cut = boundary.end() if boundary is not None else 0
        context = _STREAM_CONTEXT.search(self._pending)
        if context is not None:
            cut = min(cut, context.start())
        for sentinel in self._sentinels:
            for length in range(min(len(sentinel) - 1, len(self._pending)), 0, -1):
                if self._pending.endswith(sentinel[:length]):
                    cut = min(cut, len(self._pending) - length)
                    break
            start = self._pending.find(sentinel)
            while start >= 0:
                if start < cut < start + len(sentinel):
                    cut = start
                start = self._pending.find(sentinel, start + len(sentinel))
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(self._pending):
                if match.start() < cut < match.end():
                    cut = match.start()
        value, self._pending = self._pending[:cut], self._pending[cut:]
        return redact_text(value, extra_sentinels=self._sentinels)


def redact_value(value: Any, *, extra_sentinels: Iterable[str] = ()) -> Any:
    """Deep-redact strings inside JSON-like structures."""
    sent = tuple(s for s in extra_sentinels if s)
    if isinstance(value, str):
        return redact_text(value, extra_sentinels=sent)
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, extra_sentinels=sent) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, extra_sentinels=sent) for v in value]
    if isinstance(value, tuple):
        return [redact_value(v, extra_sentinels=sent) for v in value]
    return value


def scan_for_secrets(
    value: Any,
    *,
    extra_sentinels: Iterable[str] = (),
) -> list[str]:
    """Return class labels of residual secret hits (empty means clean)."""
    hits: list[str] = []
    sent = [s for s in extra_sentinels if s]

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            for s in sent:
                if s in obj:
                    hits.append("sentinel")
            for pat in _SECRET_PATTERNS:
                if pat.search(obj):
                    hits.append("pattern")
            return
        if isinstance(obj, Mapping):
            for v in obj.values():
                _walk(v)
            return
        if isinstance(obj, Sequence) and not isinstance(obj, (bytes, bytearray)):
            for v in obj:
                _walk(v)

    _walk(value)
    return hits


def assert_clean(value: Any, *, extra_sentinels: Iterable[str] = ()) -> None:
    """Fail closed if any residual secret remains."""
    hits = scan_for_secrets(value, extra_sentinels=extra_sentinels)
    if hits:
        raise RedactionError(
            "secret residual after redaction; refusing to seal trajectory",
            hits=sorted(set(hits)),
        )


def redact_and_assert(value: Any, *, extra_sentinels: Iterable[str] = ()) -> Any:
    cleaned = redact_value(value, extra_sentinels=extra_sentinels)
    assert_clean(cleaned, extra_sentinels=extra_sentinels)
    return cleaned


def register_sentinel(bucket: MutableMapping[str, str], name: str, value: str) -> None:
    """Helper for tests: record a sentinel value that must never appear on disk."""
    if value:
        bucket[name] = value
