# ssh environment

First-party exclusive-slot implementation for `environment: ssh`.
Implementation: `src/ageval/plugins/contrib/ssh/host.py`. Protocol verbs
only; no vendor handle leaks into ACP / `run.py`.

## Bind

```yaml
environment: ssh
```

Locators (`host` / `user` / `port` / `key_env`) are resolved at preflight.
Keys never enter the lock. A resumed Attempt probes the remote directory
(Mode A) or remote container (Mode B) and attaches to it, or uploads the
latest checkpoint when that host is gone.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `environment` |
| capabilities | `exec`, `upload`, `download`, `attach_stdio`: yes. `uid_gid`, `path_views`, `compose`: no |
| inject | — |

`attach_stdio` on A is `ssh -T -- argv`. On B it is `ssh -- docker exec -i`. Live ACP stdio over bare SSH (A) is **not** a supported path — see below.

## Parameters

Job knobs are `environment_options` (not `extensions[].options`). `${NAME}` in host/user/port/image is a locator, expanded at preflight.

| Name | Default | Purpose |
| --- | --- | --- |
| `environment_options.host` | *(required)* | SSH target. Missing → `environment_options_invalid`. |
| `environment_options.user` | unset | Remote user. Locator ok. |
| `environment_options.port` | unset (ssh default) | Remote port. Locator ok. |
| `environment_options.key_env` | unset | Env **name** of the private key. If set, that env must be present at preflight. |
| `environment_options.image` | empty | Empty → **A** (the remote machine is the environment). Non-empty existing tag → **B** (`start()` does remote `docker run`; nothing is baked at invoke). |
| `environment_options.root` | `/tmp/ageval-<id>` | Remote work root created on `start()`. |

## A vs B

`environment_options.image` empty → **A**: the remote machine is the environment.
`attach_stdio` is `ssh -T -- argv`.

A non-empty **existing** image tag → **B**: `start()` does remote `docker run`
of that tag; `attach_stdio` is `ssh -- docker exec -i`. The image must already
exist on the host. Nothing is baked at invoke.

## ACP over ssh A is a known gap

Product ACP is a **parent-only** JSON-RPC client over `attach_stdio` (stdio).
Official ACP **stdio** is a local subprocess pipe:

- [Transports (v1)](https://agentclientprotocol.com/protocol/v1/transports)

Official **remote** transport is still an RFD (Streamable HTTP + WebSocket), not
stdio tunneled over SSH:

- [Streamable HTTP & WebSocket Transport](https://agentclientprotocol.com/rfds/streamable-http-websocket-transport)
- [Introduction](https://agentclientprotocol.com/get-started/introduction)

On ssh A, `initialize` can complete and `session/new` on the same SSH pipe can
fail (`-32603`, stream destroyed) with pi-acp. That is a **transport** gap, not
a missing entry or missing key.

Until the official remote transport is consumable from the parent client:

- Do **not** claim ssh A × live ACP stdio as a supported path.
- Prefer exec-style executors (`dsh` / `nooa`) on ssh A.
- Do **not** invent a private HTTP/WS stack, a file-dump “ACP session”, or a
  second vendor stdout scrape.
- ssh B (`docker exec -i` over SSH) is a different privilege/image problem; do
  not treat a stdio-over-SSH failure as “B is broken” or the reverse.

## Other verbs

`exec` / `upload` / `download` are the Protocol surface for in-environment workers.
Directory `upload` / `download` copy **contents** (not a nested `dest/src`).
Agent Service does not harvest the environment workspace after every invoke. After
writers stop, the run phase downloads **missing** publishable files from
`/attempt/workspace` onto parent `task-artifacts`.

Not a Hub install. `ageval plugin install ssh` is rejected: the id is
reserved.
