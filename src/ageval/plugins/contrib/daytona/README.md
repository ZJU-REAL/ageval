# daytona environment

First-party exclusive-slot implementation for `environment: daytona`.

The Attempt runs in a [Daytona](https://www.daytona.io) sandbox built from
an OCI snapshot. Vendor SDK objects, snapshot names, and sandbox ids stay
in this package. Neighbors only call Protocol methods (`upload` / `exec` /
`attach_stdio`). A resumed Attempt probes the existing sandbox and attaches
to it, or uploads the latest checkpoint into a new sandbox.

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
| `environment_options.snapshot` | unset | Existing Daytona snapshot name; skip building one. Alias: `snapshot_id`. |
| `environment_options.snapshot_name` | `ageval-attempt` | Name used when this plugin creates a snapshot from a recipe. |
| `environment_options.image` | unset | Public OCI tag/digest. `latest` / `lts` / `stable` are rejected. Alias: `docker_image`. With no `snapshot`, this is snapshot-from-OCI; otherwise the task `environment/Dockerfile` is used. |
| `environment_options.timeout_seconds` | `900` | Sandbox lifetime (Daytona `auto_stop_interval`, minutes rounded up). |
| `DAYTONA_API_KEY` | *(required at preflight)* | Host env. Alias: `daytona_api_key`. Missing extra or key: lock/run skip, or the probe fails and the run does not start. |

## Bind

```yaml
environment: daytona
```

This host needs:

- `uv tool install 'ageval-cli[daytona]'` (repo checkout: `uv sync --extra daytona`)
- `DAYTONA_API_KEY` (or the scoped locator alias)

Floating tags such as `latest` / `lts` / `stable` are rejected. Missing
extra or key: lock/run **skip, or the probe fails and the run does not start**. A Hub card is not
evidence that this machine can run Daytona.

Not a Hub install. `ageval plugin install daytona` is rejected: the id is
reserved.
