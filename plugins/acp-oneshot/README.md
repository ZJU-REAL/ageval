# acp-oneshot — in-environment ACP client+server over `exec`

External `ageval.plugin/1`. **Not** first-party `executor: acp`.

Parent ACP is a JSON-RPC client on `environment.attach_stdio`. This plugin is
the other coding inlet: one `host.exec` per `invoke` starts the entry's ACP
server **and** a one-shot client *inside the environment*. ACP frames stay in the environment;
the parent learns the turn is done from process exit.

Switching pi / Claude Code / OpenCode is `options.entry` (same ids as ACP).
Do not write `executor: pi`. An environment without `attach_stdio` still lock-fails
`executor: acp`; this plugin only needs `exec`.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec` |
| chain | `after_environment_ready`, `trajectory_collect` |
| bake | — (uses the same baked ACP entries as first-party `acp`) |

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins). Same entry ids as ACP.

<!-- ageval:param-table executor=acp-oneshot -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id (codex, claude-code, pi, opencode, grok-build). Missing or unknown fails materialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model.id` | `entry-default` | Nested `model:` only. Session model id. |
| `model.reasoning.effort` | unset | Applied when the entry advertises a reasoning selector. Omit to keep the entry default. |
| `api_key` | unset | Env **locator name** projected into the **exec** env. Value never enters the lock. |
| `base_url` | unset | Projected into the exec env when the entry uses an OpenAI-compatible base. |

## Install

```bash
ageval plugin install plugins/acp-oneshot
```

Install updates `$AGEVAL_HOME/plugins` only — never edits package yaml.

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: acp-oneshot
    model:
      id: zai-coding-cn/glm-5.2
      reasoning:
        effort: xhigh
    api_key: ${ZHIPU_API_KEY}
    options:
      entry: pi
    extensions:
      - plugin: acp-oneshot
      - plugin: docker
```

Credentials are locators projected into the **exec** env.
