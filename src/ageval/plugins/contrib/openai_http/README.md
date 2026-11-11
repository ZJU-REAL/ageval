# openai-http executor

First-party exclusive-slot implementation for `executor: openai-http`.

Thin HTTP Chat Completions / Responses backend. It does not own Run identity,
PASS, or host credentials beyond a **scoped env locator** for the API key. No
Attempt environment is required; this executor does not inject `environment`.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | — (no environment) |
| chain | — |
| bake | — |

The executor capability matrix reports `stream: native-events` because both
APIs support native SSE. The wire stays one buffered JSON body unless the
profile sets `options.stream: true`.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=openai-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.stream` | false | Opt-in native SSE for api: chat and api: responses. false keeps one JSON body. |
| `options.stream_first_event_timeout_seconds` | unset | Deadline from request start to the first SSE data event. Comments and heartbeats do not satisfy it. Unset disables. |
| `options.stream_idle_timeout_seconds` | unset | Deadline from the last meaningful text/thought/tool fragment. Heartbeats do not reset it. Unset disables. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `{id: gpt-4.1-mini}` | Nested spec. Field table: `docs/design/02-schemas-and-config.md`. `supported_apis`: `chat`, `responses`. `supported_model_fields`: `id`, `api`, `reasoning_effort`, `timeout`, `watchdog`, `extra`. `extra_allowlist`: `provider` (empty would reject every extra key). |
| `model.api` | `chat` | `chat` posts `/chat/completions` and sends effort as top-level `reasoning_effort`. `responses` posts `/responses` and sends effort only as `reasoning.effort`. A gateway without `/responses` fails that call; this executor does not fall back to chat. Acceptance id for Responses is `dashscope/glm-5.2`. |
| `model.reasoning.effort` | omit | Omit does not send an effort field. `none` is sent. |
| `model.timeout` | `180` | Per-request HTTP timeout. Omit uses the clock table. `0` is rejected. |
| `model.watchdog` | `180` | Overall abort. Expiry is `TransportStall` (`openai_http_watchdog`). The parent stall loop retries only that type. An HTTP 4xx other than 408/429 is `ModelConfigError` with `repeatable=False`. Bad JSON is `ProtocolError`. Neither is retried. |
| `base_url` | unset (executor default `https://api.openai.com/v1`) | Profile sibling of `model`, not a spec field. `${ENV_NAME}` or a literal `http(s)` URL. Host `AGEVAL_OPENAI_BASE_URL` is the fallback when the field is omitted. |
| `api_key` | `OPENAI_API_KEY` | Env **locator name**, not the secret. Empty key is allowed only when `base_url` host is `127.0.0.1` / `localhost` / `::1`. |

## Streaming

```yaml
options:
  stream: true
  stream_first_event_timeout_seconds: 20
  stream_idle_timeout_seconds: 30
```

`options.stream` defaults to `false`, preserving the buffered JSON path. It
applies to both `api: chat` and `api: responses`; switching it does not change
the model, prompt, effort, token limits, or evaluation. Chat consumes
`chat.completion.chunk` frames, merges content/reasoning separately, and folds
tool-call fragments by index. Responses consumes typed `response.*` events and
requires an explicit `completed` / `incomplete` / `failed` terminal; it never
falls back to Chat Completions.

The outer `model.timeout` / `model.watchdog` ceiling is fixed at request start
and streamed chunks do not extend it. The optional first-event and idle clocks
bound "no SSE frame yet" and "no meaningful text/thought/tool fragment yet";
comments and heartbeat frames reset neither. Idle is semantic output, not any
byte. Cancellation closes the local socket even before response headers.

A malformed stream, missing terminal, unfinished tool JSON, or empty answer is
a non-retryable parse `ProtocolError`. An in-stream provider error event or a
failed provider terminal is `ProtocolError:stream_upstream_error`; only
`type`, `code`, `status_code`, `request_id`, and `message` are retained under
`metadata.stream_error`, with credentials and whole URLs redacted. HTTP
rejections use the same allowlist under `metadata.http_error`, not the raw body.
`metadata.error_origin` separates upstream failures from parse failures.
`metadata.stream_correlation` carries the exchange id plus the request
`x-client-request-id` and response `x-litellm-call-id` / `x-request-id` when
present. `stream-progress.jsonl` records only classification, counts, and
timing; it never contains provider bodies, messages, URLs, or call ids. A
length-limited or provider-incomplete ending keeps its partial text but is not
a successful completion. Provider usage is adopted only when reported; otherwise
it is explicitly unavailable, never zero. Live fragments appear as redacted
`model_turn/delta` activity rows. An unfinished token or credential prefix stays
buffered until it can be redacted safely across stream and flush boundaries;
ordinary completed text is still published live. Timing/count diagnostics land in
`backend_raw/stream-progress.jsonl`. Streaming starts showing progress earlier;
it does not guarantee a shorter generation time, and completion is not `PASS`.
Sealed invocation text events use the same incremental redaction context.

## Bind

```yaml
executor: openai-http
model:
  id: dashscope/glm-5.2
  api: responses
  reasoning:
    effort: xhigh
  timeout: 120
  watchdog: 300
  extra:
    provider:
      allow_fallbacks: false
base_url: https://openrouter.ai/api/v1
api_key: ${openrouter_api_key}
```

Native `tools=` is posted when the session has a catalog. On `api: responses`,
tools are flat `{type, name, description, parameters}`, and history uses
`function_call` / `function_call_output` items. Chat Completions keeps the
nested `function` tool object and `tool_calls`. Responses may include
`tool_calls` and reasoning `thought` events for the trajectory.
The raw HTTP body stays under `backend_raw`.

Not a Hub install. `ageval plugin install openai-http` is rejected: the
id is reserved.
