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

| Name | Default | Purpose |
| --- | --- | --- |
| `options.step_limit` | `30` | Agent step cap. `0` = unlimited. Negative / non-int values are rejected. |
| `options.cost_limit` | `0` | Cost cap. `0` = unlimited. Negative values are rejected. |
| `options.cmd_timeout` | `30` | Seconds per `host.exec` bash action. |

## Model

One profile binds one Model. `resolve_model` accepts a nested `model:` mapping or today's flat fields. The same field set in both places is `miniswe_model_conflict`.

`api_key` and `base_url` stay profile-level credential locators. They are not Model fields.

| Field | Nested | Flat (compat) | Omit |
| --- | --- | --- | --- |
| `id` | `model.id` | `model: <string>` | `openai/gpt-4o-mini` |
| `api` | `model.api` | `options.api` | `chat` |
| `reasoning.effort` | `model.reasoning.effort` | `options.reasoning_effort` | do not send |
| `timeout` | `model.timeout` | `options.timeout` | do not send an HTTP timeout. `0` means omit |
| `watchdog` | `model.watchdog` | `options.watchdog` | `180` seconds. `0`, negative, and non-finite values are rejected |
| `extra` | `model.extra` | `options.extra_body` | do not merge |

`api` short names are `chat` (Chat Completions) and `responses` (`/v1/responses`). AgentCompass spells the same wires `openai-chat` and `openai-responses`. This plugin accepts only the short names (`miniswe_api_invalid`).

`reasoning` is effort only. A declared `none` is an effort value. Other reasoning keys (`summary`, vendor budgets) belong in `extra`. `extra` cannot replace a first-class field (`id`, `api`, `reasoning.effort`, `timeout`, `watchdog`, or the deprecated `request_timeout`). That includes `extra.reasoning.effort`.

`request_timeout` is deprecated. It maps to `timeout`. `0` means omit. Do not set it beside `options.timeout`.

`timeout` is the HTTP client clock. `watchdog` is the Future abort clock. Stall reads the watchdog only. An omitted watchdog uses the 180 second cap. There is no unlimited watchdog.

For gpt-6-sol tool calls prefer `api: responses`. Chat models with an `anthropic/` (or bare `claude*`) profile id are remapped to `openai/<id>` so the gateway still sees `anthropic/…` on `/v1/chat/completions`. Each completion uses a fresh httpx client with `max_keepalive_connections=0`, sends `Connection: close`, and flushes LiteLLM's client cache before, after, and on stall retry.

Wire still applies two dark defaults that the table does not describe: an unset chat effort is sent as `reasoning_effort=none`, and an omitted timeout still uses 180 seconds for both the HTTP client and the abort clock. The omit and split change removes those defaults.

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
      id: openai/glm-5.2
      api: responses
      reasoning:
        effort: high
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

The same id still resolves from a flat profile: `model: openai/glm-5.2` plus `options.api`, `options.reasoning_effort`, `options.request_timeout`, and `options.extra_body`. A full nested file lives at `examples/agents/miniswe-default/profiles.model.yaml`.

Same harness: `Agent.session(...).invoke`. Switch with `--profiles`. PASS stays
the package evaluator.
