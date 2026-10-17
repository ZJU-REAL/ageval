# Author a `ageval.plugin/1`

Reference implementations: `plugins/nooa` (executor), `plugins/dsh`
(DeepSeek JSON-RPC, not ACP), `plugins/home-files` (chain). Design:
`docs/design/11-extension-plugins.md`.

Slots are **exclusive** and **chain** only. Do not invent extra slot kinds.

## Package layout

```text
plugins/my-mech/
├── plugin.yaml                 # format: ageval.plugin/1
├── README.md                   # required: capability + parameter tables
├── docker/Dockerfile.bake      # optional: docker image layers
├── src/my_mech/
│   ├── __init__.py             # must not import ageval Core at package import
│   ├── factory.py
│   ├── hooks.py
│   └── trajectory.py           # optional: native → ageval.trajectory.event/1
└── worker/                     # optional: in-environment entry
```

```yaml
format: ageval.plugin/1
plugin_id: my-mech
version: "0.1.0"
description: "One paragraph Hub shows above Install (CLI). Links: [text](https://example.com)."
host_requires:
  - import: my_vendor_sdk
    hint: "uv sync --extra my-mech"
slots:
  exclusive:
    - id: executor
      priority: 110
      entry: "my_mech.factory:MyMechExecutorSPI"
  chain:
    - id: trajectory_collect
      priority: 110
      entry: "my_mech.hooks:trajectory_collect"
inject:
  - service: environment
    capabilities: [exec, upload]   # ACP uses attach_stdio instead
config:
  image_layers: docker/Dockerfile.bake
```

Hub: `package_kind=plugin`. Dataset vs plugin is rejected.
`description` is optional Hub copy (one paragraph above Install (CLI)). Empty / non-string fails closed. Markdown links (`[text](https://…)`) render on Hub; other block syntax does not.

README is the Hub detail contract (previewed next to `plugin.yaml`). A plugin that
omits capability or parameter tables is unfinished. See **README contract** below.

`host_requires` allowlist keys: `import`, `file`, `hint`. Unknown keys are rejected.
`import:` is `importlib.util.find_spec` (no spawn). Core does not map plugin-id → pip extra.
docker kind does **not** consume `host_requires` (image bake does).

An environment plugin fills exclusive slot `environment`, subclasses
`ageval.plugins.base.BaseEnvironment`, and implements
`src/ageval/environments/protocol.py`. An executor subclasses `BaseExecutor`
(`supports_model` / `bind_model`). Field table: `docs/design/16-model.md`.
Do not import docker/e2b/ssh from ACP.

## Executor

The exclusive entry is the `BaseExecutor` subclass (`@executor_plugin`).
`build_executor(**kwargs)` may remain a thin wrapper. Common kwargs: `options`,
`profile_id`, `model`, `base_url`, `api_key` (locator name), `host`, `placement`,
`package_root`. A string `model` is wrapped as `{"id": ...}` before
`spec_from_factory`. `entry-default` and omit use the executor default id.

ACP attaches with `host.attach_stdio`. dsh / nooa run a baked (or uploaded)
worker with `host.exec` and `host.upload`. Missing capability → lock fails.
Core must not reconstruct a container executor by kind. Do not silently fall back to the host.

`describe()` keys already in production (copy semantics):

```text
execution_mode, tools, structured_output, session, stream,
credential_env_names, binary
```

## Trajectory

Layer B: each event row has `schema: ageval.trajectory.event/1`, `source` = this plugin id, `session_id`.
trajectory.jsonl: the `trajectory_seal` winner writes `trajectory.jsonl` (engine default). Plugins must not emit layer-C rows unless they won that slot.

`trajectory_collect` may map **this** plugin's vendor dump into layer B.
Never stamp `trajectory_source` onto another plugin's `source`. Never emit ACP `session_update`.

When the container does `import my_mech.trajectory`, package `__init__.py` must
not import the Core-touching factory.

## Image layers (docker bake)

Not a timeline slot. The environment winner reads `config.image_layers` at `host.start()`.
`executor:` alone does not bake. Context = installed plugin root (first-party
contribs use the package next to the plugin). Pin wheels / npm at image build.
No invoke-time `npm i` / floating pip. First-party ACP uses the same contract
and bakes only the bound `options.entry`. Pins come from packaged `acp_entries.json`, or from `$AGEVAL_HOME/acp-entries.json` when that file defines the bound id. A packaged id cannot be overridden. The official Attempt image does not bake home-file entries. The process started is the pinned package binary.

`${BASE_IMAGE}` is usually `ageval-attempt:base` (CPython 3.12).
Declare `ARG PIP_INDEX_URL=` after `FROM` so a parent `AGEVAL_PIP_INDEX` is
consumed. Empty means pip's default index. Do not `ENV` a blank `PIP_INDEX_URL`.
A `RUN pip` should `unset PIP_INDEX_URL` when the ARG is empty.

## Hook shape

```python
async def trajectory_collect(ctx, value, nxt):
    out = await nxt(value)
    return out
```

## Job binding (profiles, not task.yaml)

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: my-mech
    extensions:
      - plugin: my-mech
        options:
          agent: "lib.agents:MyAgent"
          method: "run"
    model:
      id: dashscope/glm-5.2
      api: responses
      reasoning:
        effort: xhigh
    api_key: ${litellm_api_key}
```

`--set /agent_profiles/<role>/options/<key>=…` writes the executor plugin row
(ACP still rejects `command` / engine keys). YAML key is `agent_profiles`.

## README contract

Hub previews this file. Authors bind against it. Keep it in the same language
as the rest of the package README. **No GitHub Issue numbers.**

Two tables are required. Copy the columns; fill from this plugin's code, not
from a sibling plugin.

### Capabilities

What this plugin **is** on the Attempt graph, and what it **needs**.

| | Value |
| --- | --- |
| export | exclusive slot it wins, if any (`environment` / `executor` / …). Exclusive winners register that slot name as a service. |
| inject | `service` + **capabilities** this plugin calls. Capability names are only those in `src/ageval/environments/protocol.py` `CAPABILITY_NAMES`: `exec`, `upload`, `download`, `attach_stdio`, `uid_gid`, `path_views`, `compose`. |
| chain | chain slots it fills (`after_environment_ready`, `trajectory_collect`, …) |
| bake | `config.image_layers` path, or omit the row |

Environment winners also list the caps they **export** (the Protocol methods they actually implement). Declaring a cap the kind cannot deliver is a bug.

Do not invent slot names. Do not write `inject: {plugin_id: e2b}`. Missing a declared cap fails at **lock**, not mid-invoke.

### Parameters

Every knob this plugin **reads**. One row per name. Columns:

| Name | Default | Purpose |
| --- | --- | --- |
| `options.agent` | *(required)* | … |
| `model` | nested `model.id` | … |

**Where the name lives** (prefix it, do not dump a second table of sources):

| Prefix | Who writes it | Who reads it |
| --- | --- | --- |
| `environment_options.<key>` | job `profiles.yaml` | environment exclusive winner |
| `options.<key>` | profile `options` then this plugin's `extensions` row; last wins | executor factory / chain hook |
| `model` / `base_url` / `api_key` | role profile (job axis) | executor factory kwargs. `api_key` is an **env locator name**, never the secret |
| `E2B_API_KEY` (host env) | host environment | preflight / invoke locators this plugin itself looks up |

Rules:

- If the plugin reads it, the row exists. If it does not read it, do not list it.
- Required knobs use `*(required)*` as Default. Omit / blank / `null` behaviour goes in Purpose.
- Allowed values and rejected cases go in Purpose, not a prose dump above the table.
- Rejected keys (ACP `command` / `engine_command` / …) get their own short table, or a Purpose note “rejected”.
- `config.image_layers` is bake input, not a job parameter — list it under Capabilities, not here.
- Do not document Core-owned fields (`environment:`, `executor:`) as this plugin's parameters.
- Secrets stay locators. Never show a real key as a default.

Template (executor):

```markdown
## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec`, `upload` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

## Parameters

| Name | Default | Purpose |
| --- | --- | --- |
| `options.agent` | *(required)* | Package-local `module:Class`. Missing → lock `extension_materialize_failed`. |
| `options.method` | `run` | Method invoked on that class. |
| `model` | nested `model.id` | Nested model object. Field table: `docs/design/16-model.md`. |
| `api_key` | `OPENAI_API_KEY` | Env **locator name**. Value never enters the lock. |
| `base_url` | `OPENAI_BASE_URL` / `litellm_base_url` | OpenAI-compatible base. |
```

Template (environment):

```markdown
## Capabilities

| | Value |
| --- | --- |
| export | exclusive `environment` |
| capabilities | `exec`, `upload`, `download`, `attach_stdio`: yes. `uid_gid`, `path_views`, `compose`: no |
| inject | — |

## Parameters

Job knobs are `environment_options` (not `extensions[].options`).

| Name | Default | Purpose |
| --- | --- | --- |
| `environment_options.host` | *(required)* | … |
```

## Typed failures

| Signal | Typical cause |
| --- | --- |
| `unknown_extension_slot` | `plugin.yaml` names a slot not in `slots.py` |
| `extension_materialize_failed` | factory/options invalid (e.g. ACP missing `options.entry`) |
| executor unbound | no in-environment bind on docker |
| bake unsatisfied | bound external executor but no `image_layers` file |
| `unsupported executor` | not installed |

Recognition ≠ this host can run ≠ image baked.

## Checklist

```bash
uv run ageval plugin install plugins/my-mech
uv run ageval plugin list
uv run ageval executors
uv run ageval lock <dataset> --task <id> --profiles path/to/profiles.yaml
uv run ageval run <dataset> --task <id> --profiles path/to/profiles.yaml --probe
```

README: Capabilities table matches `plugin.yaml` inject/slots and Protocol caps.
Parameters table matches factory / host reads (name, default, purpose). No Issue numbers.
