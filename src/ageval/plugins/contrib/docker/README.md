# docker environment

First-party exclusive-slot winner for `environment: docker`.

The Attempt runs in a container built from the task's own recipe (plus
plugin `image_layers` when declared). The official Attempt image bakes
every shipped ACP entry at **build** time. A task recipe that is not that
base still gets the bound `options.entry` from the ACP plugin layer.
Invoke does not `npm i`.
Container id, `docker exec -u/-w`, and UID/GID stay in this package.
ACP / `run.py` / Core never see `container_id`.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `environment` |
| capabilities | `exec`, `upload`, `download`, `attach_stdio`, `uid_gid`, `path_views`, `compose`: yes |
| inject | — |

`attach_stdio` is `docker exec -i`. Compose sidecars join the Attempt network by service name.

## Parameters

Job knobs are `environment_options` (not `extensions[].options`).

| Name | Default | Purpose |
| --- | --- | --- |
| `environment_options.image` | unset | Existing image tag; skip local build. Alias: `docker_image`. |
| `environment_options.platform` | this host | `docker` platform (e.g. `linux/arm64`). |
| `environment_options.network` | `bridge` | Attempt container network. A task compose file overrides this to `{project}_default`. |
| `environment_options.user` | `10001:10001` | `docker run --user` and the same identity for `exec` / `attach_stdio`. `root` / `0` / `0:0` → root. Other values must be `uid` or `uid:gid`. Unknown strings are rejected. Default still has `no-new-privileges`. |
| `environment_options.python_version` | `3.12` | CPython minor of the official Attempt base (`python:${version}-slim-bookworm`). Shape `^\d+\.\d+$`; `latest` / `3` / empty / other shapes are rejected once. The base builds as a versioned tag (e.g. `ageval-attempt:py3.13`) and the plugin rewrites the recipe's `FROM ageval-attempt:base` onto it, so 3.12 and 3.13 bases coexist. A base that cannot be pulled fails the image build once — no fallback to 3.12. The ACP entries stay baked at build time; engine versions are unaffected. |
| `environment_options.egress` | omitted | Omit = today's `bridge` (no proxy). `llm` (docker only): in-box HTTP(S) is forced through a parent allowlist proxy (`HTTP_PROXY` / `HTTPS_PROXY`). ACP stdio does not go through it. A kind that cannot enforce this fails lock. |
| `environment_options.egress_allow` | omitted | Extra hostnames on the **same map** as `egress: llm` (lowercase, no scheme / path / port). Omit = bound profile `base_url` hosts only. Empty list = no extras. Effective list = those `base_url` hosts ∪ this list, written to internal `egress_allowlist`. Present without `egress: llm`, or on a non-docker kind, fails lock. Scoring-box extras are a nested `evaluate_host.environment_options.egress_allow` and do not inherit from the agent box. |
| `AGEVAL_PIP_INDEX` (host env) | unset | When set, plugin bake layers pass it as `PIP_INDEX_URL` so image-build pip uses that index. Unset / blank = pip default. Same knob as the official Attempt image build. |

## Bind

```yaml
environment: docker
```

The host needs a working Docker engine. Gold isolation is mount +
upload-before-evaluate, not “delete the field in YAML”.

Not a Hub install. `ageval plugin install docker` is rejected: the id is
reserved.
