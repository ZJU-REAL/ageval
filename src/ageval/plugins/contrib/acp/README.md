# acp executor

First-party exclusive-slot implementation for `executor: acp`.

Parent is the **only** ACP JSON-RPC client. Placement next to miniswe,
terminus-2, and openhands:
[docs/design/05-executors-and-acp.md](../../../../../docs/design/05-executors-and-acp.md#executor-placement).
The coding-agent Target inlet is:

```yaml
executor: acp
options:
  entry: pi   # or codex / claude / another baked entry
```

Vendor private formats are translated **outside** ageval (Mode 1 shim /
Mode 2 native / Mode 3 vendor package). Do not add a second vendor stdout
scrape in this repo.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `attach_stdio` |
| chain | `after_environment_ready` (probe the environment; fail with `acp_runtime_node` when Node is below `runtime.node`; skip `install_command` when the bake already matches pin + stdio `initialize`), `trajectory_collect` |
| bake | `docker/Dockerfile.bake` — bound `options.entry` only. Pins and `runtime.node` come from packaged `acp_entries.json`, or from `$AGEVAL_HOME/acp-entries.json` when that file defines the id. A packaged id cannot be overridden. Bake installs Node 22.x when `node` is missing or older than the floor, and leaves a Node that already meets it in place. Official Attempt images bake shipped entries only. Invoke does not `npm i`. |

Missing `attach_stdio` fails at **lock**, not mid-invoke.

## Runtime floor

Every npm entry declares `runtime` in `acp_entries.json`. `runtime.node` is `>=MAJOR.MINOR.PATCH`. Maintainers store the highest published `engines.node` among the pinned packages. A pin with no `engines.node` does not raise the floor. When none of the pins publish one, the floor is `>=18.0.0`. A home-file entry includes the same field. A missing value or any other shape fails to load with `invalid_schema`.

`runtime` is one object. `node` is the required key today. Another runtime is another field on this object, plus a check on the same bake and probe path.

Bake compares `node -v` with the floor before `npm install -g`. Below the floor it installs Node 22.x and checks again. That install removes the distro `npm` and `libnode-dev` packages in the same apt transaction. NodeSource's `nodejs` conflicts with `npm`, and Ubuntu's `nodejs` pulls in `libnode-dev`. At or above the floor, the task recipe's Node stays, and the layer text does not change between builds. When Node 22.x cannot reach the floor, the image build stops with one line naming the entry id, the required floor, and the version it found. `after_environment_ready` repeats the check and ends the environment phase with `acp_runtime_node` before `install_command` or `session/new`.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=acp -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id. Shipped: codex, claude-code, pi, opencode, grok-build. Missing fails lock with acp_entry_required. |
| `options.idle_timeout_seconds` | unset | Stall ceiling during session/prompt. Any session_update or request_permission resets it. Unset or a non-positive value leaves only the wall-clock invoke timeout. Fires acp_idle_timeout. Non-numeric fails lock with acp_idle_timeout_invalid. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model.id` | `entry-default` | Nested `model:` only. Session model id. Binding is entry-specific (`config-option` vs entry-default-only). After lock, a non-default id is also written into the Attempt HOME as the engine's own overlay (Pi `models.json`, OpenCode `opencode.json`, Codex `config.toml`, Claude Code `.claude/settings.json`) so an empty environment can advertise it. Claude Code also gets `ANTHROPIC_MODEL` on the attach env. `entry-default` writes nothing. Host `~/.pi` is never copied. |
| `model.reasoning.effort` | unset | Applied when the entry advertises a reasoning selector. Omit to keep the entry default. |
| `model.api` | `chat` | Only `chat`. `responses` fails lock. |
| `api_key` | unset | Env **locator name** projected into the attach env. Value never enters the lock or the generated overlay. |
| `base_url` | unset | `${ENV_NAME}` (lock stores the locator; spawn reads env) or a literal `http(s)` URL (lock stores the URL). Included in the generated overlay when set. |

Rejected on `options` (entry-registry truth): `command`, `args`, `detect_command`, `install_command`, `version`, `acp_command`, `engine_command`, `acp_version`, `credential_env_names`.

Python ACP SDK stays on the parent. It does not go into the Attempt image.

Pi: official registry `pi-acp` (`pi --mode rpc`). Do not confuse it with
the reverse bridge `pi-shell-acp`.

Not a Hub install. `ageval plugin install acp` is rejected: the id is
reserved.
