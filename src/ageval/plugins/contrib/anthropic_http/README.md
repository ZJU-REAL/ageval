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
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `{id: claude-sonnet-4-6}` | Nested spec. `supported_apis`: `chat` (Messages, not Responses). `supported_model_fields`: `id`, `api`, `timeout`, `watchdog`, `extra`. `extra_allowlist`: `thinking`. `reasoning.effort` is rejected. |
| `model.timeout` / `model.watchdog` | `180` / `180` | Same clocks as openai-http. Omit uses the clock table. `0` is rejected. Watchdog expiry is a repeatable transport error. |
| `model.extra.thinking` | omit | Copied onto the Messages body. |
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
