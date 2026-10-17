# miniswe — mini-swe-agent executor plugin

External `ageval.plugin/1`. **Not** first-party ageval core.

Drives [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) as a
**The model stays on the host:** the LLM client stays on the parent; every bash action goes
through the injected `environment` service (`host.exec`). This is **not** ACP.
Name is the mechanism (`miniswe`), not a benchmark.

```python
from minisweagent.agents.default import DefaultAgent
from minisweagent.models.litellm_model import LitellmModel

agent = DefaultAgent(LitellmModel(model_name=...), env)  # env calls host.exec
agent.run(prompt)
```

A kind that cannot `exec` fails at `ageval lock`, not mid-invoke. Model HTTP
stays on the parent (mini-swe-agent's `LitellmModel` client). The upstream is
whatever that client routes: an OpenAI-compatible `base_url`, or a LiteLLM
prefix (`openai/`, `openrouter/`, `anthropic/`, …). Credentials are locators
projected into the parent HTTP client; they never enter the lock.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).
These limits are agent knobs, not Model fields.

<!-- ageval:param-table executor=miniswe -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.stream` | `true` on `api: chat` | Chat Completions use SSE when true. false sends one JSON body. An omitted key is true, so AGEVAL_MINISWE_CHAT_STREAM=0 does not turn a profile run off. Responses ignores this. |
| `options.step_limit` | 30 | Agent step cap. 0 is unlimited. Negative values are rejected. |
| `options.cost_limit` | 0 | Cost cap. 0 is unlimited. Negative values are rejected. |
| `options.cmd_timeout` | 30 | Seconds per host.exec bash action. Negative values are rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

## Model

One profile binds one nested `model:`. The field table is [docs/design/16-model.md](../../docs/design/16-model.md). This plugin does not parse a second shape. A string `model` or a flat model key (`api`, `reasoning_effort`, `timeout`, `request_timeout`, `watchdog`, `extra_body`) fails lock as `model_config`.

`api_key` and `base_url` stay profile-level credential locators. They are not Model fields.

| | Value |
| --- | --- |
| `supported_apis` | `chat`, `responses` |
| `supported_model_fields` | `id`, `api`, `reasoning_effort`, `timeout`, `watchdog`, `extra` |
| `extra_allowlist` | `reasoning`, `provider` |

`api` short names are `chat` (Chat Completions) and `responses` (`/v1/responses`). Anything else is `model_api_invalid`.

`reasoning.effort` is the only first-class reasoning field. A declared `none` is a value and is sent. Omit means do not send. Other reasoning keys (`summary`, vendor budgets) belong in `extra`. `extra` cannot replace a first-class field, including `extra.reasoning.effort`. An extra key outside the allowlist fails lock.

`timeout` is the HTTP client clock. Omit or `0` means the client has no timeout. `watchdog` is the Future abort clock. Stall reads the watchdog only. An omitted watchdog uses the 180 second cap. There is no unlimited watchdog. `0`, negative, and non-finite watchdog values fail at lock. Stall aborts on the watchdog and writes `miniswe_watchdog:` to stderr. That expiry is a transport failure. A config error does not stall-retry.

## Chat and responses

| Model field | `api: chat` | `api: responses` |
| --- | --- | --- |
| `id` | JSON `model` | JSON `model` |
| `reasoning.effort` set | `reasoning_effort` | `reasoning.effort`, merged over `extra.reasoning`, effort last |
| `reasoning.effort` omit | `reasoning_effort` is absent | `reasoning.effort` is absent. `extra.reasoning` keys such as `summary` are still sent |
| `timeout` | HTTP client argument | HTTP client argument |
| `watchdog` | Future abort. Stall reads this clock only | Future abort. Stall reads this clock only |

HTTP 400, 401, 403, 404, and 422 stop the call as `ModelConfigError`. 408, 429, and 5xx stay transport failures and may stall. An api that cannot represent a declared effort fails the same way, before stall retries.

For gpt-6-sol tool calls prefer `api: responses`. Chat models with an `anthropic/` (or bare `claude*`) profile id are remapped to `openai/<id>` so the gateway still sees `anthropic/…` on `/v1/chat/completions`. Chat posts SSE unless `options.stream` is false. Responses stays one POST. Each completion uses a fresh httpx client with `max_keepalive_connections=0`, sends `Connection: close`, and flushes LiteLLM's client cache before, after, and on stall retry.

`api_key` defaults to the locator names `OPENAI_API_KEY` / `litellm_api_key` / `LITELLM_API_KEY`. Omit the key on loopback `base_url` (`127.0.0.1` / `localhost` / `::1`). `base_url` defaults to `OPENAI_BASE_URL` / `litellm_base_url` / `LITELLM_BASE_URL`.

## Install

```bash
uv tool install 'ageval-cli[miniswe]'   # or: uv sync --extra miniswe in this repo checkout
ageval plugin install plugins/miniswe
```

Install updates `$AGEVAL_HOME/plugins` only — never edits package yaml.

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: miniswe
    model:
      id: dashscope/glm-5.2
      api: responses
      reasoning:
        effort: xhigh
      timeout: 120
      watchdog: 300
      extra:
        reasoning:
          summary: auto
    api_key: ${litellm_api_key}
    base_url: ${litellm_base_url}
    extensions:
      - plugin: miniswe
        options:
          step_limit: 30          # 0 = unlimited
          cost_limit: 0           # 0 = unlimited
          cmd_timeout: 30
      - plugin: docker
```

A full nested file lives at `examples/agents/miniswe-default/profiles.model.yaml`. Responses on a gateway without `/responses` stays a gateway requirement. This plugin does not fall back to chat.

Same harness: `Agent.session(...).invoke`. Switch with `--profiles`. PASS stays
the package evaluator.
