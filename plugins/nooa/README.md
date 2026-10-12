# nooa — ecosystem executor plugin (NVIDIA OO Agents)

External `ageval.plugin/1` package. **Not** first-party ageval core (only ACP is first-party).

This plugin binds ageval profiles to **[NVIDIA-labs OO Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents)**.
The parent does not import NVIDIA nooa or LiteLLM as the success path. It
injects the `environment` service (`exec`, `upload`), uploads the worker and
the task's agent module into the box, and runs the worker with `host.exec`.

Package-local agents should subclass `nooa.Agent` and use generation methods.
Plain deterministic classes (e.g. `FixedAnswerAgent`) still run inside the box
without a network.

Profile `base_url` + `api_key` (env locator) project into the exec env as
`OPENAI_BASE_URL` / `OPENAI_API_KEY`. Values never enter the lock.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec`, `upload` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

A kind that cannot `exec` / `upload` fails at `ageval lock`, not mid-invoke.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

| Name | Default | Purpose |
| --- | --- | --- |
| `options.agent` | *(required)* | Package-local `module:Class` (subclass `nooa.Agent`, or a deterministic class). Missing → lock `nooa_options_agent_required`. |
| `options.method` | `run` | Method invoked on that class. |
| `model` | `openai/gpt-4.1-mini` | Model id projected into the worker. |
| `api_key` | `OPENAI_API_KEY` / `litellm_api_key` | Env **locator name**. Value never enters the lock. Omit on loopback `base_url` (`127.0.0.1` / `localhost` / `::1`). |
| `base_url` | `OPENAI_BASE_URL` / `litellm_base_url` / `AGEVAL_OPENAI_BASE_URL` | OpenAI-compatible base projected as `OPENAI_BASE_URL`. |

## Install

```bash
uv tool install 'ageval-cli[nooa]'   # or: uv sync --extra nooa in this repo checkout
ageval plugin install plugins/nooa
```

Install updates `~/.ageval/plugins` (or `$AGEVAL_HOME/plugins`) only — **never** edits
`profiles.yaml` / `ageval.yaml` / `task.yaml`.

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: nooa
    extensions:
      - plugin: nooa
        options:
          agent: "lib.agents:JsonlAggAgent"   # package-local nooa.Agent
          method: "run"
      - plugin: docker
    model:
      id: openai/glm-5.2
      reasoning:
        effort: xhigh
    api_key: ${litellm_api_key}          # env locator
    # base_url: http://127.0.0.1:8000/v1   # optional; else litellm_base_url / OPENAI_BASE_URL
```

## minimal-demo smoke (real API)

```bash
ageval plugin install plugins/nooa
unset AGEVAL_OFFLINE_AGENT
ageval run examples/datasets/minimal-demo \
  --profiles examples/datasets/minimal-demo/profiles.nooa.yaml
```

Evidence for a successful invoke includes worker metadata
`execution_location: attempt-container`. A kind that cannot `exec` fails at
`ageval lock`, not mid-invoke.

## Recognition ≠ this host can run ≠ image baked

- **install** → Recognition only (`plugin list` / executor visible)
- **`host_requires`** → local kind needs the `nooa` import (`uv tool install 'ageval-cli[nooa]'` / repo checkout `uv sync --extra nooa`); docker bake does not
- **profiles `executor: nooa`** → exclusive slot winner (+ model / base_url / api_key)
- **`extensions: [{plugin: nooa}]`** → opt-in bake / trajectory collect
- **`--probe`** → binding-aware feasibility; no Agent, no bake
- **image baked** → `Dockerfile.bake` installs `nooa` into the box Python. The worker script is uploaded at invoke and run with `host.exec` + projected credentials
