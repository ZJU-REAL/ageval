# 06 — Extension Plugins: Exclusive Slots, Chain Slots, and Dependency Injection

To allow replacing execution environments and agent executors while supporting cross-cutting hooks (runtime preparation, task setup, trajectory enrichment) without coupling plugins to concrete classes, **ageval** provides a declarative plugin architecture based on **exclusive slots**, **chain slots**, and **service dependency injection (`export` / `inject`)**.

Canonical slot identifiers live in `src/ageval/plugins/slots.py`. The master phase emission order is defined in [ARCHITECTURE.md](../../ARCHITECTURE.md) § Extension Emit Map and [01-core-lifecycle.md](01-core-lifecycle.md).

---

## 1. Core Concepts: Slots, Services, and Decoupled `inject`

| Concept | Role in the Runtime | Where Defined |
| --- | --- | --- |
| **Plugin Slot (`slot`)** | Lifecycle extension point where a plugin attaches to an Attempt. | `src/ageval/plugins/slots.py` |
| **Named Service (`service`)** | Runtime capability interface callable by other plugins via `ctx.services.require("<name>")`. | Exclusive-slot implementations automatically export a same-named service; plugins may also declare `exports.services`. |

Plugins never import each other's implementation modules or hardcode `plugin_id` dependencies:

| Mechanism | Normative Contract | Architectural Constraint |
| --- | --- | --- |
| **`export`** | The bound implementation of an exclusive slot (e.g., `environment`) is registered in `ctx.services` under the slot name. | Never leaks `container_id`, sandbox handles, or vendor SDK objects above the protocol. |
| **`inject`** | A plugin declares `inject: [{service: "environment", capabilities: ["attach_stdio"]}]` in `plugin.yaml`. | Depends on the service name and required `EnvironmentCapabilities`, never on a specific `plugin_id` (`docker` or `e2b`), and never branches on `if kind == ...`. |
| **Protocol calls** | Consuming plugins call only `EnvironmentProvider` methods (`attach_stdio`, `exec`, `upload`, `download`, `visible_path`). | Executors never construct `docker exec` commands or assume host-local filesystem paths. |

---

## 2. Two-Stage Static Contract Validation

1. **Import-time registration check (`@environment_plugin` / `@executor_plugin`)**:
   - First-party and external environment and executor classes subclass `BaseEnvironment` or `BaseExecutor` (`src/ageval/plugins/base.py`) and register via `@environment_plugin` or `@executor_plugin` (`src/ageval/plugins/decorators.py`).
   - At decoration time, the decorator verifies that all abstract lifecycle methods, all methods corresponding to `True` flags on `capabilities`, and all required model contract attributes (`supported_apis`, `supported_model_fields`, `extra_allowlist`) are implemented on the class. Any violation raises `PluginContractError` (`kind="plugin_contract"`) immediately.
2. **Lock-time graph and model check (`ageval lock`)**:
   - `ExtensionRegistry.resolve` builds an `ExtensionGraph` per role profile, selects exclusive-slot implementations, orders chain slots by ascending `priority`, verifies `requires_environment` and `inject` capabilities against the bound `environment`, and calls `BaseExecutor.supports_model(spec)` on the executor class without instantiating it ([02-schemas-and-config.md](02-schemas-and-config.md), [05-executors-and-acp.md](05-executors-and-acp.md)).
   - Third-party YAML-only factory plugins lacking `@executor_plugin` emit `YamlOnlyExecutorWarning` prior to `2027-01-15` and raise `PluginContractError` immediately when `AGEVAL_STRICT_MODEL_CONTRACT=1` is set (and unconditionally starting `2027-01-15`).

---

## 3. Exclusive Slots vs. Chain Slots

| Slot Category | Binding Granularity | Registered Slots |
| --- | --- | --- |
| **Exclusive slot** | Binds a single implementation per resolution graph and exports it as a same-named service. | `environment` (Attempt-wide), `executor` (per role profile in `agent_profiles`), `evaluation_runtime` (Attempt-wide, default `default`), `trajectory_seal` (Attempt-wide, default `default`) |
| **Chain slot** | Priority-ordered hook chain `async def hook(ctx, value, nxt)` executed sequentially. | `before_environment`, `after_environment_ready`, `environment_setup`, `after_environment`, `before_run`, `before/after_agent_open`, `before/after_agent_invoke`, `normalize_agent_result`, `before/after_agent_close`, `after_run`, `before_evaluate`, `after_evaluate`, `trajectory_collect`, `trajectory_enrich`, `summary_enrich`, `cleanup_report` |

- Optional plugins not listed in `extensions` never enter the execution chain or Docker `image_layers`.
- `bind_evaluation` (`PASS` / `FAIL`), Attempt identity minting, and `finally cleanup` are engine invariants and cannot be overridden by plugins.

---

## 4. Plugin Manifest Schema (`plugin.yaml` — `ageval.plugin/1`) and Resolution Priority

```yaml
# Environment plugin manifest example
format: ageval.plugin/1
plugin_id: e2b
description: Provision the Attempt environment on E2B cloud sandboxes.
slots:
  exclusive:
    - id: environment
      entry: e2b_plugin:E2BHost

# Executor plugin manifest example
format: ageval.plugin/1
plugin_id: acp
description: Parent ACP JSON-RPC client over environment attach_stdio.
slots:
  exclusive:
    - id: executor
      entry: acp.executor:AcpExecutor
  chain:
    - id: after_environment_ready
      entry: acp.hooks:ensure_runtime
inject:
  - service: environment
    capabilities: [attach_stdio]
```

External plugin packages (`plugins/nooa/plugin.yaml`, `plugins/dsh/plugin.yaml`, etc.) may additionally declare `host_requires` (host binary/env checks) and `config.image_layers` (baked into Docker images during `host.start`).

### Priority and resolution rules
```text
profiles.environment + agent_profiles.<role>.executor + extensions
  → ExtensionRegistry.resolve → ExtensionGraph (one graph per role profile; Attempt-wide environment must agree)
       exclusive: explicit profile choice wins; otherwise lowest numerical priority wins (ties fail lock)
       chain:     ordered by ascending priority (DEFAULT_PRIORITY = 1000; smaller number runs earlier)
  → recorded in lock.extension_bindings and hashed into lock.digest
```

`ageval plugin install` installs external packages into `~/.ageval/plugins` without mutating any `profiles.yaml`.

---

## 5. First-Party Builtin vs. External Plugins and Chain Hook Signatures

1. **First-party builtin plugins (`src/ageval/plugins/contrib/`)**: Reserved short IDs `local`, `docker`, `e2b`, `ssh`, `daytona`, `acp`, `openai-http`, and `anthropic-http`. Listed in `services/registry/packages/builtin_plugins.json` on Hub `/plugins`; always available without `ageval plugin install` (publishing or installing a package colliding with a reserved ID is rejected).
2. **External plugins (`plugins/` or Hub)**: `nooa`, `dsh`, `miniswe`, `terminus-2`, `openhands`, `acp-oneshot`, `home-files`, and `agent-skills`. Each plugin ships `plugin.yaml` and a `README.md` containing **Capabilities** and generated **Parameters** tables.
3. **Four distinct readiness states**: **Listed in Hub catalog** $\neq$ **Installed in `~/.ageval/plugins`** $\neq$ **Host satisfies `host_requires`** $\neq$ **Baked into Docker image layer**.

### Chain-slot hook contract
```python
async def trajectory_collect(ctx: AttemptCtx, value: Any, nxt: Callable[[Any], Awaitable[Any]]) -> Any:
    out = await nxt(value)
    return out
```

- `FAIL_OPEN_SLOTS` (`before_run`, `after_run`, `trajectory_collect`, `trajectory_enrich`, `summary_enrich`, `cleanup_report`) log a warning fact on exception and allow execution to continue; exceptions in any other slot fail the enclosing phase.
- `trajectory_collect` and `trajectory_enrich` may add JSON-safe keys under `extra` on invocation records without removing canonical `usage` fields.
- `summary_enrich` runs once after `trajectory_seal` with initial value `{}`; each plugin writes only under `value[<plugin_id>]` ([07-evidence-and-analysis.md](07-evidence-and-analysis.md)).
