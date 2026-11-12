# anthropic-http executor

First-party exclusive-slot implementation for `executor: anthropic-http`.

Thin Anthropic **Messages** HTTP backend. It does not own Run identity,
PASS, or host credentials beyond a **scoped env locator** for the API
key. No Attempt environment is required; this executor does not inject
`environment`.

This is not a dialect of `openai-http`. Chat Completions (including
Anthropic's official OpenAI-compatible layer) stay on `openai-http`.
Messages-only endpoints and native `tool_use` / `thinking` use this
kind.

SDK `tools=` / `messages=` remain OpenAI-shaped. Translation to
`/messages` + `tool_use` happens in this executor.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | — (no environment) |
| chain | — |
| bake | — |

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=anthropic-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.max_tokens` | 4096 | Required Messages max_tokens. Positive int. Non-int values are rejected. |
| `options.anthropic_version` | 2023-06-01 | anthropic-version request header. Non-string values are rejected. |
| `options.omit_temperature` | false | Omit temperature for providers requiring their default. |
| `options.stream` | false | Opt-in native Messages SSE; false retains a single JSON response. |
| `options.stream_first_event_timeout_seconds` | unset | First SSE data deadline; None disables. |
| `options.stream_idle_timeout_seconds` | unset | Semantic output idle deadline; pings do not reset it. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `{id: claude-sonnet-4-6}` | Nested spec. `supported_apis`: `chat` (Messages, not Responses). `supported_model_fields`: `id`, `api`, `timeout`, `watchdog`, `extra`. `extra_allowlist`: `thinking`, `output_config`. `reasoning.effort` is rejected. |
| `model.timeout` / `model.watchdog` | `180` / `180` | Same clocks as openai-http. Omit uses the clock table. `0` is rejected. Watchdog expiry is a repeatable transport error. |
| `model.extra.thinking` | omit | Copied onto the Messages body. |
| `model.extra.output_config` | omit | Copied onto the Messages body. `output_config.effort: max` is the Messages effort field. |
| `base_url` | unset (executor default `https://api.anthropic.com/v1`) | `${ENV_NAME}` (lock stores the locator) or a literal `http(s)` URL. Host `AGEVAL_ANTHROPIC_BASE_URL` is the fallback when the field is omitted. |
| `api_key` | `ANTHROPIC_API_KEY` | Env **locator name**, not the secret. Empty key is allowed only when `base_url` host is `127.0.0.1` / `localhost` / `::1`. |

## Bind

```yaml
executor: anthropic-http
model:
  id: claude-sonnet-4-6
  extra:
    thinking:
      type: enabled
      budget_tokens: 2000
    output_config:
      effort: max
base_url: https://api.anthropic.com/v1
api_key: ${ANTHROPIC_API_KEY}
options:
  max_tokens: 4096
```

Native `tools=` from the session catalog is posted as Anthropic
`tools`. Responses may include `tool_use` (mapped to `AgentResult.tool_calls`)
and `thinking` (thought events). The raw HTTP body stays under
`backend_raw`.

Not a Hub install. `ageval plugin install anthropic-http` is rejected: the
id is reserved.

## Native Messages streaming

Enable SSE with `options.stream: true`; the default remains `false`. Both modes
return the same SDK response and native tool-call fields. Text, thinking,
signatures, redacted thinking, and fragmented tool arguments are assembled by
block index. Signatures and redacted blocks are not answer text. Initial usage
and cumulative final usage are merged without counting tokens twice.

```yaml
options:
  stream: true
  stream_first_event_timeout_seconds: 25
  stream_idle_timeout_seconds: 25
  upstream_stall_seconds: 0
  # Only for an endpoint that rejects an explicit temperature:
  omit_temperature: true
```

The optional positive first-event and meaningful-output idle limits do not reset
the overall invocation/watchdog or task `limits`. The idle clock starts when
response headers arrive. Pings and comments do not reset it. `omit_temperature` defaults to `false` and
preserves `temperature: 0` unless explicitly enabled. A third-party Messages
endpoint uses `base_url` ending in `/v1`; the executor appends `/messages`.

While receiving output, the executor records redacted partial model-turn
snapshots in `activity.jsonl` at most four times per second. Only the completed
turn is projected into subsequent conversation history; an interrupted turn
remains aborted with partial text/thinking.
Tool-use snapshots retain the block index, tool id/name and redacted unfinished
JSON arguments in `partial_tool_calls`, including a final snapshot on abort.
The standard `trajectory.jsonl` is
sealed after invocation, with separate thinking and answer content. Use
`--keep-recovery-state` to retain activity after settlement and
`--keep-vendor-raw` to retain the counts/timings-only
`backend_raw/stream-progress.jsonl` diagnostic journal.

A complete stream requires closed blocks, a usable text/tool response, a valid
stop reason, and `message_stop`. `stop_reason: refusal` is a finished exchange:
the invocation is `model_refusal` (`ok: false`, not retried) and is not
`stream_incomplete` or `stream_empty_answer`. Premature EOF, malformed tool JSON, provider
error events, thinking-only responses, and `max_tokens` truncation fail explicitly;
partial text is never published as a successful answer. Provider error details
are bounded and redacted. Received usage on failure is marked partial, not billed
as a finished turn. Stream completion is not benchmark `PASS`.

Cancellation shuts down established local sockets even while waiting for response
headers. DNS resolution, TCP connection and TLS setup still depend on their HTTP
socket timeout; `reader_stopped: false` is reported if such a reader has not
finished within the cleanup grace period. Closing a local connection does not
prove remote provider computation stopped. Streaming exposes progress; it does
not guarantee faster or successful completion of a long task.
