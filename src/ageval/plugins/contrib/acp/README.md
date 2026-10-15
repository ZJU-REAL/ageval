# acp executor

First-party exclusive-slot winner for `executor: acp`.

Parent is the **only** ACP JSON-RPC client. The coding-agent Target inlet is:

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
| chain | `after_environment_ready` (probe the box; skip `install_command` when the bake already matches pin + stdio `initialize`), `trajectory_collect` |
| bake | `docker/Dockerfile.bake` — bound `options.entry` only. Pins come from packaged `acp_entries.json`, or from `$AGEVAL_HOME/acp-entries.json` when that file defines the id. A packaged id cannot be overridden. Official Attempt images bake shipped entries only. Invoke does not `npm i`. |

Missing `attach_stdio` fails at **lock**, not mid-invoke.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id. Shipped: `codex`, `claude-code`, `pi`, `opencode`, `grok-build`. Missing → lock `acp_entry_required`. |
| `options.idle_timeout_seconds` | unset | Stall ceiling during `session/prompt`. Any `session_update` or `request_permission` resets it. Unset / ≤0 → wall-clock invoke `timeout` only. Fires `acp_idle_timeout` (still capped by Parent wall). Non-numeric → lock `acp_idle_timeout_invalid`. |
| `model.id` | `entry-default` | Nested `model:` only. Session model id. Binding is entry-specific (`config-option` vs entry-default-only). After lock, a non-default id is also written into the Attempt HOME as the engine's own overlay (Pi `models.json`, OpenCode `opencode.json`, Codex `config.toml`, Claude Code `.claude/settings.json`) so an empty box can advertise it. Claude Code also gets `ANTHROPIC_MODEL` on the attach env. `entry-default` writes nothing. Host `~/.pi` is never copied. |
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
