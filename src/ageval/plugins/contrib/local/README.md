# local environment

First-party exclusive-slot implementation for `environment: local`.

The Attempt uses a real directory tree on this host. In-environment paths
(`/attempt/workspace`, `/attempt/home`, `/attempt/evaluation`, artifacts)
map onto those directories. `exec` is a real subprocess; `attach_stdio`
hands ACP a live `Popen` pipe. Gold stays off the Agent mount and is
uploaded only before evaluate.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `environment` |
| capabilities | `exec`, `upload`, `download`, `attach_stdio`: yes. `uid_gid`, `path_views`, `compose`: no |
| inject | — |

## Parameters

This kind reads no `environment_options`.

| Name | Default | Purpose |
| --- | --- | --- |
| — | — | No job knobs. The process must be able to write the work root. |

## Bind

```yaml
environment: local
```

No extra Python package. The process must be able to write the work root.
This is a production kind, not a mock environment.

Not a Hub install. `ageval plugin install local` is rejected: the id is
reserved.
