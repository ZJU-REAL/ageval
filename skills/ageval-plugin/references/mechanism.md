# Plugin mechanism

Design authority: `docs/design/11-extension-plugins.md`. This note is for
authoring agents only; it does not own new contract.

## Registry

- First-party contrib: `acp`, `openai-http`, `anthropic-http`, `local`, `docker`, `e2b`, `ssh`, `daytona`. No product mock executor.
- External `ageval plugin install` joins the same table.
- `profiles.executor` / `environment` pick exclusive winners. Chain slots are opt-in via `extensions`.
- `extensions:` is the opt-in list (`- plugin: nooa`, or `slots: [...]`, or `{slot, plugin}`). Installed-but-unlisted plugins stay off MULTI chains and off the image.
- Local path install and `ageval run` use the short `plugin.yaml` id. Hub publish/install uses `org/name`.
- README is the public contract Hub previews: export / inject capabilities, and the parameters this plugin reads. `plugin.yaml` is the machine manifest; the README tables are what authors bind against.
- Resolve: explicit binding > lower priority wins; a tie with no explicit pick is rejected.
- `ageval lock` writes the resolved graph as `extension_bindings` (plugin_id / slot / source / priority / digest).

Do not revive the deleted `ageval.agent_executors` entry-point bypass.

## Class registration

`@environment_plugin` and `@executor_plugin` live in `ageval.plugins.decorators`. Decorating a class (the class statement, which runs on first import) checks the contract, then calls `ExtensionRegistry.exclusive` on the process registry (`get_global_registry`). There is no second candidate table. The class object is the exclusive-slot factory (`is_factory=True`), so `kind` and `capabilities` are readable before it is constructed. Existing contrib modules still register with `register_*_contrib`.

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

## Slots

Ids live in `src/ageval/plugins/slots.py`. Exclusive: `environment`, `executor`, `evaluation_runtime`, `trajectory_seal`. Chain: environment ready/setup, run bookends, agent open/invoke/close, evaluate bookends, `trajectory_collect` / `trajectory_enrich`, `summary_enrich`, `cleanup_report`.

`evaluation_runtime` / `trajectory_seal` have engine defaults (`plugin_id: default`). No job-field sugar; replace only with an explicit `extensions` row. PASS still enters only through `bind_evaluation`.

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
