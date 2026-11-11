"""Streaming activity retains credential context across every flush boundary."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.evidence.redaction import IncrementalTextRedactor, redact_text
from ageval.plugins.contrib.openai_http.executor import _redact_stream_events
from ageval.plugins.http_activity import ModelTurnDeltaWriter


@pytest.mark.parametrize(
    "secret",
    [
        "sk-abcdef1234567890",
        "Authorization: Bearer credential-value",
        "api_key = credential-value",
        "cookie: session-value",
        "postgresql://user:password-value@host/db",
        "/Users/test/.codex/auth.json",
        "explicit sentinel with spaces",
    ],
)
@pytest.mark.parametrize("explicit_sentinel", [False, True])
def test_redaction_matches_whole_text_at_every_split(secret: str, explicit_sentinel: bool) -> None:
    text = f"ordinary progress {secret} followed by more progress "
    sentinels = (secret,) if explicit_sentinel else ()
    for split in range(len(text) + 1):
        redactor = IncrementalTextRedactor(extra_sentinels=sentinels)
        result = redactor.feed(text[:split]) + redactor.feed(text[split:])
        result += redactor.feed("", final=True)
        assert result == redact_text(text, extra_sentinels=sentinels)


def test_pattern_redaction_survives_character_fragments() -> None:
    text = "progress Authorization: Bearer sk-abcdef1234567890 more text "
    redactor = IncrementalTextRedactor()
    result = "".join(redactor.feed(char) for char in text)
    result += redactor.feed("", final=True)
    assert result == redact_text(text)


@pytest.mark.parametrize("channel", ["assistant", "thought", "tool"])
@pytest.mark.parametrize("prefix", ["", "x" * 4094 + " "])
def test_activity_redacts_across_flush_and_chunk_boundaries(
    tmp_path: Path, channel: str, prefix: str
) -> None:
    secret = "sk-abcdef1234567890"
    log = ActivityLog.open(tmp_path / "activity.jsonl", sentinels=(secret,))
    scope = ActivityScope(log, session_id="s", invoke_request_id="i")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "hello"}])
    writer = ModelTurnDeltaWriter(SimpleNamespace(activity=scope), 1)
    for part in (prefix + "sk-", "abcdef1234567890", " safe progress "):
        writer.append(channel, part)
        writer.flush()
    writer.close()
    text = "".join(str(row.payload["text"]) for row in log.records if row.status == "delta")
    assert text == prefix + "[REDACTED:secret] safe progress "
    assert secret not in log.path.read_text()
    assert "abcdef1234567890" not in log.path.read_text()


def test_live_safe_text_is_released_before_terminal() -> None:
    redactor = IncrementalTextRedactor()
    assert redactor.feed("visible progress ") == "visible progress "
    assert redactor.feed("sk-") == ""
    assert redactor.feed("abcdef1234567890 ") == "[REDACTED:secret] "


@pytest.mark.parametrize("channel", ["assistant", "thought"])
def test_invocation_events_share_redaction_context(channel: str) -> None:
    secret = "sk-abcdef1234567890"
    events = tuple(
        {"kind": "text", "channel": channel, "text": char, "source": "openai-http"}
        for char in "visible " + secret + " finished"
    )
    result = _redact_stream_events(events, (secret,))
    assert "".join(event["text"] for event in result) == "visible [REDACTED:secret] finished"
