# e2b environment

First-party exclusive-slot implementation for `environment: e2b`.

The Attempt runs in an [E2B](https://e2b.dev) cloud sandbox built from the
task recipe. Vendor SDK objects stay in this package. Neighbors only call
Protocol methods (`upload` / `exec` / `attach_stdio`).

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
| `environment_options.image` | unset | Skip Dockerfile build when set. Alias: `docker_image`. |
| `environment_options.template_id` | unset | Exact E2B dashboard alias; skip recipe hash / Dockerfile. |
| `environment_options.template` | `ageval-attempt` | Name prefix when this plugin hashes a recipe into `name__digest`. |
| `environment_options.timeout_seconds` | `900` | Sandbox lifetime passed to `Sandbox.create`. |
| `E2B_API_KEY` | *(required at preflight)* | Host env. Alias: `e2b_api_key`. Missing extra or key: lock/run skip, or the probe fails and the run does not start. |

## Bind

```yaml
environment: e2b
```

This host needs:

- `uv tool install 'ageval-cli[e2b]'` (repo checkout: `uv sync --extra e2b`)
- an E2B API key in the scoped credential locator

Missing extra or key: lock/run **skip, or the probe fails and the run does not start**. Do not treat a
Hub catalog card as “this machine can run e2b”.

Not a Hub install. `ageval plugin install e2b` is rejected: the id is
reserved.
