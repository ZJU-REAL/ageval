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

| Name | Default | Purpose |
| --- | --- | --- |
| `options.step_limit` | `30` | Agent step cap. `0` = unlimited. Negative / non-int values are rejected. |
| `options.cost_limit` | `0` | Cost cap. `0` = unlimited. Negative values are rejected. |
| `options.cmd_timeout` | `30` | Seconds per `host.exec` bash action. |
| `options.request_timeout` | `180` | Seconds for one litellm/openai `completion` HTTP call (`timeout=`). Fail-fast into upstream_stall instead of silent multi-minute hangs. `0` = omit (legacy litellm/openai defaults). |
| `options.reasoning_effort` | omit | Optional OpenAI-shaped Chat Completions `reasoning_effort`. Empty / omit = do not send. Non-string values are rejected. |
| `options.extra_body` | omit | Optional mapping merged as-is into the parent completion kwargs (after `reasoning_effort`). Vendor-native keys (OpenRouter `reasoning` / `provider`, vLLM extras, …). Omit / empty = do not merge. Non-mapping values are rejected. Rejects `model` / `api_key` / `api_base` / `drop_params` / `timeout` / `request_timeout`. Conflicting keys: `request_timeout` still wins for `timeout=`. |
| `model` | `openai/gpt-4o-mini` | Upstream model id on the parent client (`openai/…`, `openrouter/…`, `anthropic/…`, or any id the `base_url` gateway accepts). |
| `api_key` | `OPENAI_API_KEY` / `litellm_api_key` / `LITELLM_API_KEY` | Env **locator name** for the parent HTTP client. Omit on loopback `base_url` (`127.0.0.1` / `localhost` / `::1`). |
| `base_url` | `OPENAI_BASE_URL` / `litellm_base_url` / `LITELLM_BASE_URL` | OpenAI-compatible base (`api_base`). Point at OpenRouter, DashScope, a local gateway, etc. |

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
    extensions:
      - plugin: miniswe
        options:
          step_limit: 30          # 0 = unlimited
          cost_limit: 0           # 0 = unlimited
          cmd_timeout: 30
          extra_body:             # optional; vendor-native body keys
            reasoning:
              max_tokens: 2000
      - plugin: docker
    model: openai/glm-5.2
    api_key: ${litellm_api_key}
    base_url: ${litellm_base_url}
```

Same harness: `Agent.session(...).invoke`. Switch with `--profiles`. PASS stays
the package evaluator.
