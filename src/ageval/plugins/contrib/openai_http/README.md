# openai-http executor

First-party exclusive-slot winner for `executor: openai-http`.

Thin HTTP Chat backend. It does not own Run identity, PASS, or host
credentials beyond a **scoped env locator** for the API key. No Attempt
box is required; this executor does not inject `environment`.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | — (no box) |
| chain | — |
| bake | — |

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `{id: gpt-4.1-mini}` | Nested spec. Field table: `docs/design/16-model.md`. `supported_apis`: `chat`, `responses`. `supported_model_fields`: `id`, `api`, `reasoning_effort`, `timeout`, `watchdog`, `extra`. `extra_allowlist`: `provider` (empty would reject every extra key). |
| `model.api` | `chat` | `chat` posts `/chat/completions` and sends effort as top-level `reasoning_effort`. `responses` posts `/responses` and sends effort only as `reasoning.effort`. A gateway without `/responses` fails that call; this executor does not fall back to chat. Acceptance id for Responses is `dashscope/glm-5.2`. |
| `model.reasoning.effort` | omit | Omit does not send an effort field. `none` is sent. |
| `model.timeout` | invoke timeout | Per-request HTTP timeout. |
| `model.watchdog` | `180` | Overall abort. Expiry is a repeatable transport error (`openai_http_watchdog`), which the parent stall loop retries. A config error is not retried: an HTTP 4xx other than 408/429 returns `ModelConfigError:HTTPError:<code>` with `repeatable=False`, and the parent stall loop treats any executor's bare `HTTPError:4xx` (except 408/429) the same way. |
| `base_url` | unset (executor default `https://api.openai.com/v1`) | Profile sibling of `model`, not a spec field. `${ENV_NAME}` or a literal `http(s)` URL. Host `AGEVAL_OPENAI_BASE_URL` is the fallback when the field is omitted. |
| `api_key` | `OPENAI_API_KEY` | Env **locator name**, not the secret. Empty key is allowed only when `base_url` host is `127.0.0.1` / `localhost` / `::1`. |

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

`RunTerminal.completed` is not PASS. PASS still comes from the independent
evaluator.

Not a Hub install. `ageval plugin install openai-http` is rejected: the
id is reserved.
