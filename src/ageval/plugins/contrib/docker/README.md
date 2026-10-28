# docker environment

First-party exclusive-slot implementation for `environment: docker`.

The Attempt runs in a container built from the task's own recipe (plus
plugin `image_layers` when declared). The official Attempt image
(``attempt/`` in this package, shipped in the wheel) bakes every shipped
ACP entry at **build** time. ``ageval run`` pulls
``ghcr.io/zju-real/ageval-attempt:<cli-version>`` into local
``ageval-attempt:base`` when that tag is missing; a miss builds from the
packaged Dockerfile. A task recipe that is not that
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

`attach_stdio` is `docker exec -i`. With `environment/compose.yaml`, the services in that file come up first and the Attempt joins `{project}_default`, so a service is reachable by name. On that network the Attempt is also registered as hostname `main` (`docker run --network-alias main`). Harbor sidecars dial the agent by that name (for example `KV_HOST=main`); ageval does not start a compose service called `main`, so the alias is what makes the name resolve. `network_mode: service:<name>` starts the Attempt with `docker run --network container:<that service's container>`, so `127.0.0.1` is that service's `127.0.0.1`, and the `main` alias is not added. A run with no compose file does not add it either. The Attempt stays a separate `docker run`.

## Parameters

Job knobs are `environment_options` (not `extensions[].options`).

| Name | Default | Purpose |
| --- | --- | --- |
| `environment_options.image` | unset | Existing image tag; skip local build. Alias: `docker_image`. |
| `environment_options.platform` | this host | `docker` platform (e.g. `linux/arm64`). |
| `environment_options.network` | `bridge` | Attempt container network when there is no compose file. A task compose file joins `{project}_default` unless `network_mode` is `service:<name>`. Joining that project network also sets `--network-alias main`. |
| `environment_options.network_mode` | omitted | `service:<name>` starts the Attempt with `--network container:<that service's container id>`. Other values leave the network unchanged. Same key on task `parameters.network_mode`, or `services.main.network_mode` in `environment/docker-compose.yaml` when that file is not the compose-up file. Job value wins, then parameters, then the file. Scoring containers do not read it. |
| `environment_options.cap_add` | omitted | Capability names passed to `docker run --cap-add` (for example `SYS_PTRACE`). `no-new-privileges` stays. Same key on `parameters.cap_add`, or `services.main.cap_add` in `environment/docker-compose.yaml`. |
| `environment_options.main_environment` | omitted | `KEY=VALUE` entries on `docker run -e`. Overrides the same names already baked as image ENV. A bare name with no value fails once and is not taken from the parent environment. Names that point at the Docker daemon, such as `DOCKER_HOST`, are not passed in. Same key on `parameters.main_environment`, or `services.main.environment` in `environment/docker-compose.yaml`. Not written to the lock or to evidence. |
| `environment_options.user` | `10001:10001` | `docker run --user` and the same identity for `exec` / `attach_stdio`. `root` / `0` / `0:0` → root. Other values must be `uid` or `uid:gid`. Unknown strings are rejected. Default still has `no-new-privileges`. |
| `environment_options.python_version` | `3.12` | CPython minor of the official Attempt base (`python:${version}-slim-bookworm`). Shape `^\d+\.\d+$`; `latest` / `3` / empty / other shapes are rejected once. The base builds as a versioned tag (e.g. `ageval-attempt:py3.13`) and the plugin rewrites the recipe's `FROM ageval-attempt:base` onto it, so 3.12 and 3.13 bases coexist. A base that cannot be pulled fails the image build once — no fallback to 3.12. The ACP entries stay baked at build time; engine versions are unaffected. |
| `environment_options.egress` | omitted | Omit = today's `bridge` (no proxy). `llm` (docker only): in-container HTTP(S) is forced through a parent allowlist proxy (`HTTP_PROXY` / `HTTPS_PROXY`). ACP stdio does not go through it. A kind that cannot enforce this fails lock. |
| `environment_options.egress_allow` | omitted | Extra hostnames on the **same map** as `egress: llm` (lowercase, no scheme / path / port). Omit = bound profile `base_url` hosts only. Empty list = no extras. Effective list = those `base_url` hosts ∪ this list, written to internal `egress_allowlist`. Present without `egress: llm`, or on a non-docker kind, fails lock. Scoring-container extras are a nested `evaluate_host.environment_options.egress_allow` and do not inherit from the agent container. |
| `AGEVAL_PIP_INDEX` (host env) | unset | When set, plugin bake layers pass it as `PIP_INDEX_URL` so image-build pip uses that index. Unset / blank = pip default. Same knob as the official Attempt image build. |
| `AGEVAL_APT_MIRROR` (host env) | unset | Replaces Debian package sources during Attempt image builds and plugin bake. With Clash/Tailscale **fake-ip**, mirrors such as `aliyun` can be unreachable, causing apt to stall or return 404 during bake. Prefer an explicitly reachable CDN in the task Dockerfile; verify mirror connectivity before batch image builds. |

## Task resource parameters

When the job `environment` is `docker`, these task `parameters` change the Attempt container. They are not `environment_options`. Omitted keys, `gpus: 0`, and an empty `gpu_types` leave today's `docker run` argv. `storage_mb` is not read. Other environment kinds do not apply these keys.

| Name | Default | Purpose |
| --- | --- | --- |
| `parameters.cpus` | unset | Positive number → `docker run --cpus`. `0` adds nothing. |
| `parameters.memory_mb` | unset | Positive integer → `--memory <n>m`. `0` adds nothing. |
| `parameters.gpus` | `0` | Positive count → `--gpus`. The host must show that many GPUs via `nvidia-smi` or start fails with `environment_gpu_unavailable` before any container is created. |
| `parameters.gpu_types` | `[]` | Case-insensitive substrings of the GPU name. Non-empty selects `--gpus device=<index,...>`. Non-empty with `gpus: 0` requires one matching GPU. |
| `parameters.verifier_gpus` | `0` | Scoring container only. Positive count uses the same `gpu_types` filter and the same unavailable error. Scoring CPU and memory are not read from parameters. |

A compose sidecar that already sets `cpus` or `mem_limit` and does not set `deploy.resources.limits` gets an override that copies that limit into `deploy.resources.limits`. Sidecars that declare no limit stay as authored. The agent container stays `docker run`.

A bad shape fails lock (`invalid_schema` at `/parameters/<key>`).

## Bind

```yaml
environment: docker
```

The host needs a working Docker engine. Gold isolation is mount +
upload-before-evaluate, not “delete the field in YAML”.

Not a Hub install. `ageval plugin install docker` is rejected: the id is
reserved.
