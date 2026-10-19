# Plugin mechanism

Design authority: `docs/design/11-extension-plugins.md`. This note is for
authoring agents only; it does not own new contract.

## Registry

- First-party contrib: `acp`, `openai-http`, `anthropic-http`, `local`, `docker`, `e2b`, `ssh`, `daytona`. No product mock executor.
- External `ageval plugin install` joins the same table.
- `profiles.executor` / `environment` select exclusive-slot implementations. Chain slots are opt-in via `extensions`.
- `extensions:` is the opt-in list (`- plugin: nooa`, or `slots: [...]`, or `{slot, plugin}`). Installed-but-unlisted plugins stay off MULTI chains and off the image.
- Local path install and `ageval run` use the short `plugin.yaml` id. Hub publish/install uses `org/name`.
- README is the public contract Hub previews: export / inject capabilities, and the parameters this plugin reads. `plugin.yaml` is the machine manifest; the README tables are what authors bind against.
- Resolve: explicit binding > lower priority value; a tie with no explicit selection is rejected.
- `ageval lock` writes the resolved graph as `extension_bindings` (plugin_id / slot / source / priority / digest).

Do not revive the deleted `ageval.agent_executors` entry-point bypass.

## Class registration

`@environment_plugin` and `@executor_plugin` live in `ageval.plugins.decorators`. Decorating a class (the class statement, which runs on first import) checks the contract, then calls `ExtensionRegistry.exclusive` on the process registry (`get_global_registry`). There is no second candidate table. The class object is the exclusive-slot factory (`is_factory=True`), so `kind` and `capabilities` are readable before it is constructed.

## Builtin loading (scheme A)

First-party environments and executors load from explicit module tuples in `ageval.plugins.builtin`. `bootstrap_registry` calls `load_builtin_environments()` then `load_builtin_executors()`. Each loader imports only the names on its tuple (`importlib.import_module`). That import is what runs `@environment_plugin` / `@executor_plugin` when the class is decorated. The tuples are the builtin set. Nothing walks `contrib/` or any other directory.

| Tuple | Modules |
| --- | --- |
| `_BUILTIN_ENVIRONMENT_MODULES` | `ageval.plugins.contrib.local.host`, `ageval.plugins.contrib.docker.host`, `ageval.plugins.contrib.e2b.host`, `ageval.plugins.contrib.daytona.host`, `ageval.plugins.contrib.ssh.host` |
| `_BUILTIN_EXECUTOR_MODULES` | `ageval.plugins.contrib.acp.executor`, `ageval.plugins.contrib.openai_http.executor`, `ageval.plugins.contrib.anthropic_http.executor` |

`miniswe`, `nooa`, `dsh`, and `acp-oneshot` are not on `_BUILTIN_EXECUTOR_MODULES`. Each stays an installed plugin loaded by `load_installed_plugins` after `ageval plugin install`. The exclusive entry is the `BaseExecutor` class. Do not add them to the builtin executor tuple.

Commenting out a tuple entry disables that contrib. Adding a builtin means editing the tuple. Do not add a scan or a `@builtin_*` discovery pass.

Until a listed class is itself the exclusive factory, `load_builtin_*` still calls that module's `register_*_contrib` for the same list entry. A class object defined in the listed module is not replaced. ACP's `after_environment_ready`, `trajectory_collect`, and `attach_stdio` inject stay registered with the executor. Those `register_*_contrib` helpers are shims for today's undecorated contrib, not a second loader.

```python
@environment_plugin(priority=100, source="first-party")
class DockerHost(BaseEnvironment):
    kind = "docker"  # exclusive-slot plugin id
    capabilities = EnvironmentCapabilities(
        exec=True, upload=True, download=True, attach_stdio=True,
        uid_gid=True, path_views=True, compose=True,
    )

@executor_plugin(priority=120, source="first-party")
class OpenAIHttpExecutor(BaseExecutor):
    kind = "openai-http"
    requires_environment = False
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset({
        "id", "api", "reasoning_effort", "timeout", "watchdog", "extra",
    })
    extra_allowlist = frozenset({"provider"})  # required; empty frozenset() is valid
```

Decorator arguments are `priority` (default `100`) and `source` (default `"first-party"`). `kind` is the class attribute, the same id an exclusive slot uses today (`docker`, `openai-http`, …).

Environment attributes read at registration: `kind`, `capabilities` (an `EnvironmentCapabilities` instance). Executor attributes: `kind`, `requires_environment` (base default `True` counts), `supported_apis`, `supported_model_fields`, `extra_allowlist`. `extra_allowlist` must be present even when empty. An empty allowlist means lock rejects every extra key. That lock check is not part of registration.

Registration raises `PluginContractError` (`kind` is `plugin_contract`) and does not insert a row when:

- the class is not a subclass of `BaseEnvironment` / `BaseExecutor`
- an executor is missing a callable `invoke`, `close`, `supports_model`, or `bind_model`
- `extra_allowlist`, `supported_apis`, or `supported_model_fields` is absent (an explicit empty `frozenset` is valid; a non-`frozenset` is not)
- `capabilities.exec` / `upload` / `download` / `attach_stdio` is true and that method is missing or not callable
- `preflight`, `start`, or `stop` is missing or not callable

`uid_gid`, `path_views`, and `compose` have no methods. `api` outside `supported_apis`, and an extra key outside `extra_allowlist`, are lock checks. Registration does not perform them.

## Lock contract

After exclusive winners resolve, and before the lock document is written:

- `requires_environment` true: the environment winner must be bound, and every capability on that executor's `environment` inject must be present. Missing either raises `PluginContractError` (`kind` `plugin_contract`). This is not a stall.
- A `BaseExecutor` winner with a nested `model:`: `resolve_model`, then the class method `supports_model(spec)`. Lock does not construct an instance. An `api` outside `supported_apis`, an active field outside `supported_model_fields`, or an `extra` key outside `extra_allowlist` (an empty allowlist rejects every key) raises `ModelConfigError`. The lock is not written.
- A yaml-only executor (a factory that is not a `BaseExecutor` class, so it cannot declare an allowlist): with the env unset, `source: first-party` raises `PluginContractError` and every other source warns with `YamlOnlyExecutorWarning` until 2027-01-15. The warning names that date. On that date every source is rejected, including when the env is `0`, `false`, `no`, or `off`. `AGEVAL_STRICT_MODEL_CONTRACT=1` (also `true`, `yes`, `on`, or `strict`) raises for every source before the date as well.
- A `BaseExecutor` winner parses profile `options` with its frozen `Options` class at lock. An unknown key fails the lock and names the field. A close name is suggested by edit distance. Flat model keys are still `model_flat_rejected` and are checked before `Options.parse`.

Registration still does not check `api` or extra keys. An omitted `model` on a class winner is not sent, so `supports_model` is skipped. `requires_environment` is still checked.

## Slots

Ids live in `src/ageval/plugins/slots.py`. Exclusive: `environment`, `executor`, `evaluation_runtime`, `trajectory_seal`. Chain: environment ready/setup, run bookends, agent open/invoke/close, evaluate bookends, `trajectory_collect` / `trajectory_enrich`, `summary_enrich`, `cleanup_report`.

`evaluation_runtime` / `trajectory_seal` have engine defaults (`plugin_id: default`). They are replaced only with an explicit `extensions` row. PASS still enters only through `bind_evaluation`.

A public slot must have a production emit, or design / ARCHITECTURE must mark it non-public. No silent dead SPI.

Agent emit chain:

```text
open_session → pin graph → before/after_agent_open
invoke       → before_agent_invoke → executor.invoke → after_agent_invoke
             → normalize_agent_result
record       → trajectory_collect → enrich → trajectory_seal writes trajectory.jsonl
             → summary_enrich (later steps still run if this hook fails; Attempt summary.extra)
close        → before_agent_close → executor.close → after_agent_close
```

## Coexists with ACP

The default coding-agent inlet remains first-party `executor: acp` + `- plugin: acp` / `options.entry`.
An external plugin is an optional mechanism. The **same `run.py`** switches via
profiles. ACP is not the trajectory schema authority.

## Priority convention

`DEFAULT_PRIORITY = 1000`. **Lower number runs first (chain) / wins first (exclusive).**
First-party ACP is about `100`; the nooa example uses `110`. Explicit profile
binding beats the number.
