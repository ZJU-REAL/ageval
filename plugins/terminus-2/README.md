# terminus-2 — host-loop tmux executor

External `ageval.plugin/1`. The model HTTP client stays on the parent. Each
command batch is typed into a tmux session inside the attempt environment
through `environment.exec`. This is not ACP, and it does not shell out to a
Harbor CLI.

If `tmux -V` fails during setup, the plugin installs tmux with the box package
manager (`apt-get`, `apk`, `dnf`, `microdnf`, or `yum`) as root and checks
again. A failed install is `environment_setup_failed` /
`terminus2_tmux_unavailable`. The evaluator machine does not need tmux.
`docker/Dockerfile.bake` can install tmux at image build; that layer is an
optimization.

Placement next to ACP, miniswe, and openhands:
[docs/design/05-executors-and-acp.md](../../docs/design/05-executors-and-acp.md#executor-placement).

`task_complete` ends the episode. The package evaluator still owns PASS.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=terminus-2 -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.parser` | json | Command batch format: json or xml. Anything else is rejected. |
| `options.step_limit` | 30 | Model turns before the episode stops. 0 is unlimited. |
| `options.cmd_timeout` | 60 | Seconds per environment.exec, including tmux install and pane capture. |
| `options.pane_width` | 160 | tmux pane width in columns. |
| `options.pane_height` | 40 | tmux pane height in rows. |
| `options.max_format_errors` | 3 | Malformed replies returned to the model before the episode stops. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

## Model

One profile binds one nested `model:`. `api` is `chat` or `responses`.
`api_key` and `base_url` are locators. Loopback `base_url` (`127.0.0.1`,
`localhost`, `::1`) may omit the key. Other hosts need
`OPENAI_API_KEY`, `litellm_api_key`, or `LITELLM_API_KEY`.

| | Value |
| --- | --- |
| `supported_apis` | `chat`, `responses` |
| `supported_model_fields` | `id`, `api`, `reasoning_effort`, `timeout`, `watchdog`, `extra` |
| `extra_allowlist` | `reasoning`, `provider` |

`timeout` is the HTTP clock. `watchdog` aborts one POST. Omit uses the clock
table (180 seconds). HTTP 400, 401, 403, 404, and 422 are config errors.
408, 429, and 5xx retry on the parent stall inside the episode.

## Install

```bash
ageval plugin install plugins/terminus-2
```

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: terminus-2
    model:
      id: dashscope/glm-5.2
      api: chat
      reasoning:
        effort: max
    api_key: ${litellm_api_key}
    base_url: ${litellm_base_url}
    extensions:
      - plugin: terminus-2
        options:
          parser: json
          step_limit: 30
          cmd_timeout: 60
      - plugin: docker
```

A packaged profile lives at `examples/agents/terminus-2-default/agent.yaml`.
