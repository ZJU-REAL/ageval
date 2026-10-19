---
name: ageval-plugin
description: >
  Author ageval.plugin/1: exclusive and chain slots, registry resolve, environment
  or executor implementations, image_layers bake. Use for plugin.yaml, attach_stdio hosts,
  trajectory_collect, README capability and parameter tables. Not an app store.
  Never invent slots.
---

# ageval plugins

Core declares slots in `src/ageval/plugins/slots.py`. Plugins implement them.

| Kind | Meaning | Examples |
| --- | --- | --- |
| exclusive | One bound implementation per graph = same-name service | `environment`, `executor`, `evaluation_runtime`, `trajectory_seal` |
| chain | `(ctx, value, nxt)` | `after_environment_ready`, `environment_setup`, `trajectory_collect` |

`ageval plugin install` writes `~/.ageval/plugins` only and never rewrites `profiles.yaml`.

`inject`: `service: environment`. ACP requires `attach_stdio`. In-environment workers (`dsh` / `nooa`) require `exec` and `upload`. Do not hardcode `plugin_id: e2b`.

Name plugins by mechanism (`acp`, `e2b`, `daytona`, `ssh`, `nooa`). First-party plugins live in `src/ageval/plugins/contrib/`. External packages live under `plugins/`.

Recognition ≠ host runnable ≠ image baked. Missing extras or credentials skip or fail preflight; never fake green results.

Every plugin ships a Hub-visible `README.md` with two required tables: **Capabilities** (export / inject) and **Parameters** (name, default, purpose). Capability names must belong to `src/ageval/environments/protocol.py` `CAPABILITY_NAMES`.

Authoring: [references/authoring.md](references/authoring.md). Mechanism: [references/mechanism.md](references/mechanism.md). Design: `docs/design/11-extension-plugins.md`.
