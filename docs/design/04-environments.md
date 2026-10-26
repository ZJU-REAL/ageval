# 04 — Execution Environments (`EnvironmentProvider` and `BaseEnvironment`)

Execution environments plug into the Attempt-wide exclusive slot `environment`, subclass `BaseEnvironment` (`src/ageval/plugins/base.py`), and implement the `EnvironmentProvider` protocol (`src/ageval/environments/protocol.py`). Vendor SDKs (`docker`, `e2b`, `daytona`, `ssh`) remain strictly encapsulated inside `src/ageval/plugins/contrib/<kind>/`.

Canonical in-environment paths are `/attempt/workspace`, `/attempt/home`, `/attempt/artifacts`, and `/attempt/evaluation`.

---

## 1. `EnvironmentProvider` Protocol and `BaseEnvironment` Contract

```python
CAPABILITY_NAMES: frozenset[str] = frozenset({
    "exec",
    "upload",
    "download",
    "attach_stdio",
    "uid_gid",
    "path_views",
    "compose",
})

class EnvironmentProvider(Protocol):
    kind: str                                    # "local" | "docker" | "e2b" | "ssh" | "daytona"
    capabilities: EnvironmentCapabilities        # Boolean flags for CAPABILITY_NAMES
    python_command: tuple[str, ...]              # e.g., ("python3",)

    async def preflight(self) -> None: ...
    async def start(self, *, force_build: bool = False) -> None: ...
    def placement(self) -> Placement: ...        # Opaque target_id + user + workdir/home
    def visible_path(self, box_path: str) -> str: ...
    async def exec(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        user: str | None = None,
        service: str | None = None,
    ) -> ExecResult: ...
    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None: ...
    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None: ...
    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
    ) -> StdioTransport: ...
    async def stop(self, *, delete: bool) -> None: ...
```

### `BaseEnvironment` registration invariants
All environment plugins subclass `BaseEnvironment` and register via `@environment_plugin`. At import time, the decorator verifies that:
1. `kind`, `capabilities` (`EnvironmentCapabilities`), and `python_command` are defined on the class;
2. Abstract methods `preflight`, `start`, `stop`, `placement`, and `visible_path` are implemented;
3. Every optional method (`exec`, `upload`, `download`, `attach_stdio`) whose corresponding flag on `capabilities` is `True` is implemented on the subclass (otherwise raising `PluginContractError`).

---

### Probe, attach, and `/tmp/.ageval-state`

Every environment kind implements `runtime_handle()`, `probe(handle)`, and `attach(handle)`. `probe` returns `absent`, `idle`, or `busy`. Recovery files live at `/tmp/.ageval-state` inside the environment, not under `/attempt`, so the evaluated agent does not see the nonce, cursor, or checkpoint helper. On `local` and `docker` the same files are the host directory `<attempt>/state`, beside the bind-mounted box; docker mounts that directory at `/tmp/.ageval-state`. `local` publishes that host path to child processes as `AGEVAL_STATE_DIR`. When the workspace is not kept, `stop(delete=True)` removes `<attempt>/state` with `box/`, and a sealed Attempt also drops that directory along with `checkpoints/`. `e2b`, `daytona`, and `ssh` reconnect to the handle, then read `/tmp/.ageval-state/{nonce,cursor.json,inflight.pid,last_exit.json}`. The command wrapper writes `inflight.pid` while a command runs, streams stdout and stderr to `inflight.output`, and atomically writes `last_exit.json` (`request_id`, `exit_code`, `stdout`, `stderr`) when the command exits. `attach_stdio` records its process in the same pid file, so a live ACP or worker process makes `probe` return `busy`. Those three remote kinds also run `/tmp/.ageval-state/checkpoint_sync.py` to download a delta of `/attempt/{workspace,home,artifacts}` into the parent checkpoint, and `checkpoint_sync.py wrap` is the command wrapper that keeps the command output. Recovery reuses an `idle` environment whose nonce and cursor match the activity log. A missing or diverged environment is discarded with `discard(handle)` and started again, then restored from `checkpoints/`. `discard` stops the recorded container or sandbox and leaves the attempt directory in place. `local` does not delete that directory. Live cloud probes are skipped when credentials are absent.

## 2. Environment Kinds and Capability Matrix

Task `requires.environment` defaults to `[]`. When non-empty, `ageval lock` verifies `requires.environment ⊆ capabilities` (and verifies plugin `inject` capability requirements against the same table), failing fast with `capability_missing` if any required capability is absent.

| Capability Flag | `local` | `docker` | `e2b` | `ssh` | `daytona` |
| --- | --- | --- | --- | --- | --- |
| `exec` / `upload` / `download` | yes | yes | yes | yes | yes |
| `attach_stdio` | Local subprocess pipe | `docker exec -i` | yes (E2B SDK stdin/stdout stream) | `ssh -T` (Mode A) / remote `docker exec -i` (Mode B) | yes (Daytona session stdin + log stream) |
| `uid_gid` / `path_views` | no | yes | no | no | no |
| `compose` | no | yes | no | no | no |

- **`path_views` vs. `gold` isolation**: `path_views` supports per-role mount and UID views within a single container (provided by `docker`). Default reference material (`gold`) isolation does not require `path_views`; it is enforced on every environment kind by delaying `evaluation/` upload until the `evaluate` phase (or using `evaluate_host.isolated: true`).
- **Shared Dockerfile recipe**: A task's `environment/Dockerfile` (or `docker_image`) is shared across `docker` (local image build), `e2b` (`Template.from_dockerfile`), and `daytona` (`Image.from_dockerfile` or pinned OCI image tag; floating tags `latest`, `lts`, and `stable` are rejected).

---

## 3. Official Base Image and Plugin Layer Baking (`docker`)

The official Attempt base image recipe lives at `src/ageval/plugins/contrib/docker/attempt/` (packaged inside `ageval-cli`). On `host.start()`, `DockerHost` resolves the base image in order:
1. Reuse local tag `ageval-attempt:base` if present;
2. Otherwise pull `ghcr.io/zju-real/ageval-attempt:<cli-ver>` and tag it as `ageval-attempt:base`;
3. On pull miss, build `ageval-attempt:base` locally from the packaged Dockerfile.

### Image build invariants
- **`python_version` selection**: `ARG PYTHON_VERSION` defaults to `"3.12"`. When `environment_options.python_version` specifies another minor version (matching `^\d+\.\d+$`, e.g., `"3.13"`), `FROM ageval-attempt:base` in the task Dockerfile is rewritten to `ageval-attempt:py3.13`. Pull or build failure raises `environment_start_failed` without silently falling back to `3.12`.
- **Plugin `image_layers` stacking**: Tasks may also start from arbitrary base images (e.g., `FROM ubuntu:24.04`). After building the task Dockerfile, `docker` stacks `config.image_layers` from active plugins in resolution order. The ACP layer installs only the pinned npm package(s) for the bound `options.entry` at image build time — never running `npm i` or floating `npx` during `invoke`.
- **Node.js runtime floor (`runtime.node`)**: Each ACP entry declares `runtime.node` (`>=MAJOR.MINOR.PATCH`). If the task image's `node` binary is absent or below the floor, the ACP image layer installs Node 22.x and re-verifies the floor at build time while leaving task system packages untouched.
- **Harbor build context and `/app` symlink binding**: Under `--layout harbor`, the Docker build context is `tasks/<id>/environment/` (or `tests/` for a standalone `tests/Dockerfile` verifier). On container startup, `DockerHost` copies any existing `/app` contents into `/attempt/workspace` and replaces `/app` with a symlink to `/attempt/workspace` (failing with `harbor_app_alignment` if `/app` cannot be linked).

---

## 4. Docker `environment_options`, Hardware Limits, and Compose Sidecars

### 4.1 `environment_options` keys (`docker`)

| Option Key | Default | Behavioral Contract |
| --- | --- | --- |
| `image` / `docker_image` | unset | Uses a pre-built image tag and skips local Dockerfile build. |
| `platform` | Host architecture | Target OCI platform passed to `docker build` / `docker run`. |
| `network` | `"bridge"` | Docker network mode (`"none"` disables networking). When `environment/compose.yaml` starts sidecars, the Attempt container joins `{project}_default` with `--network-alias main` unless `network_mode: service:<name>` is set. |
| `egress` | unset | When set to `"llm"`, routes container HTTP(S) traffic through a parent-process allowlist proxy (`HTTP_PROXY` / `HTTPS_PROXY`). |
| `egress_allow` | `[]` | Must be paired with `egress: llm`. Lowercase hostnames (no scheme or port) unioned with the `base_url` hostnames of bound role profiles. |
| `user` | `"10001:10001"` | Container user for `docker run --user`, `exec`, and `attach_stdio` (`"root"`, `"0"`, or `"0:0"` runs as root). `--security-opt no-new-privileges` is always applied. |
| `python_version` | `"3.12"` | Base image Python version (`^\d+\.\d+$`). |

### 4.2 CPU, Memory, and GPU resource limits (`task.yaml` `parameters`)

Hardware limits are declared under `parameters` in `task.yaml` and enforced by `DockerHost.start` (ignored on non-Docker environments):

| Parameter Key | Type | When Omitted, `0`, or Empty | `docker` Enforcement |
| --- | --- | --- | --- |
| `cpus` | Non-negative `int` or `float` (booleans rejected) | No `--cpus` flag | `docker run --cpus <n>` |
| `memory_mb` | Non-negative `int` (booleans rejected) | No `--memory` flag | `docker run --memory <n>m` |
| `gpus` | Non-negative `int` (booleans rejected) | No `--gpus` flag | Queries `nvidia-smi` before container creation; requests `<n>` GPUs. |
| `gpu_types` | Non-empty `list[str]` | No model-name filter | Requires visible host GPU names to match at least one substring (case-insensitive). |
| `verifier_gpus` | Non-negative `int` (booleans rejected) | Scoring container gets no GPUs | Allocates `<n>` GPUs (filtered by `gpu_types`) to the isolated scoring container. |

If `gpus > 0` or `gpu_types` is non-empty and the host lacks sufficient matching GPUs (or `nvidia-smi` is unavailable), the `environment` phase fails fast with `environment_gpu_unavailable` before starting any Compose sidecars or Attempt containers. For Compose sidecars declaring `cpus` or `mem_limit` without `deploy.resources.limits`, `DockerHost` generates a runtime Compose overlay so limits are enforced consistently.

### 4.3 Copying `/attempt` back to the host

`download` of a `/attempt` path first copies the bind mount as the host user. Root inside the container can leave `0600` files and `0700` directories on that mount. The host copy then raises `PermissionError` or `shutil.Error`. Download removes the destination — chmod retries apply only to that leftover tree, including host-owned `0444` / `0555` residue — and replaces it with one `docker cp` tar stream extracted as the host user. Modes on the mount stay as the agent wrote them. `upload` onto `/attempt` stays a host-side copy. Paths outside `/attempt`, and any copy for a compose service, stay on `docker cp` / `docker compose cp`.

### 4.4 Docker Compose sidecars and `services.main` parity

Both `environment/compose.yaml` and `environment/docker-compose.yaml` are recognized (`compose.yaml` takes precedence when both exist). `DockerHost` strips `services.main` (and any `depends_on` pointing to `main`) before running `docker compose up -d` for auxiliary services, because the Attempt itself always runs in a dedicated `docker run` container. If `main` was the only service declared, no Compose project is started.

For the Attempt container, `network_mode`, `cap_add`, and `main_environment` merge in priority order (later overrides earlier; scoring containers ignore all three):
1. `services.main` fields in `environment/docker-compose.yaml` (when not used as the primary `compose.yaml`);
2. `parameters.{network_mode,cap_add,main_environment}` in `task.yaml`;
3. `environment_options.{network_mode,cap_add,main_environment}` in `profiles.yaml`.

- `network_mode: service:<name>` attaches the Attempt container to that sidecar's network namespace via `--network container:<sidecar_cid>` (mutually exclusive with `egress: llm`; does not register `--network-alias main`).
- `main_environment` injects `-e KEY=VALUE` flags while stripping host Docker daemon variables (`DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_CONFIG`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH`, `DOCKER_API_VERSION`, `SSL_CERT_FILE`).

---

## 5. `attach_stdio` Transport Implementations

`attach_stdio(argv, *, placement, env, request_id=None)` spawns a foreground process inside the active environment and returns a `StdioTransport` (`stdin`, `stdout`, `stderr`, `terminate()`, `wait()`) so `AcpExecutor` operates identically across all five environment kinds. When `request_id` is set, the process is the `inflight.pid` that `probe` uses for `busy`:

| Environment Kind | `attach_stdio(argv)` Implementation |
| --- | --- |
| `local` | Local `subprocess.Popen(argv, start_new_session=True)` in the Attempt work root. |
| `docker` | `subprocess.Popen(["docker", "exec", "-i", "-u", user, "-w", workdir, *env_flags, container_id, *argv])`. |
| `ssh` Mode A (remote host) | `subprocess.Popen(["ssh", "-T", *ssh_opts, target, "--", *escaped_argv])`. |
| `ssh` Mode B (remote container) | `start()` runs `docker run -d` on the remote host; `attach_stdio` runs `ssh -T ... -- docker exec -i <cid> ...`. |
| `e2b` | E2B SDK background command bridged onto OS file descriptors via `send_stdin` and stdout event pump threads. |
| `daytona` | Daytona session command bridged onto OS pipes via `send_session_command_input` and `get_session_command_logs`. |

When `E2B_API_KEY`, `DAYTONA_API_KEY`, or SSH credentials are absent, `preflight` (and `ageval run --probe`) fails closed before creating any cloud sandbox or remote container.
