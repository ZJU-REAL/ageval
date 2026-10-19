# dsh — DeepSeek Harness executor plugin

External `ageval.plugin/1` package. **Not** first-party ageval core.

Drives [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) over
the official Python JSON-RPC SDK (`deepseek-harness-sdk` + bundled
`dsh-jsonrpc-agent`). This is **not** ACP: DSH's shipped ACP wire is too thin
for ageval evidence (no tools / reasoning / usage; model is not on
`config_options`).

The parent does not import the harness. It injects the `environment` service
(`exec`, `upload`), uploads the worker into the environment, and runs it with
`host.exec`. Credentials stay locators until invoke, then project into the
exec env as `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`.

Profile `model` is passed on `initialize`. Sessions persist under the Attempt
home (`/attempt/home/dsh-sessions`), not the task workspace.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec`, `upload` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

A kind that cannot `exec` / `upload` fails at `ageval lock`, not mid-invoke.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=dsh -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.composition` | slim | Bundled compositions/<name>.cordis.yml. Path separators and a leading dot are rejected. Setting permission with omit or slim switches to sandboxed. |
| `options.permission` | unset | read-only, workspace-write, or danger-full-access. Omit keeps unrestricted slim tools. Invalid values are rejected. Sets DSH_PERMISSION_MODE. File-tool writes are fenced; bash redirect can still write. |
| `options.max_tokens` | unset | Omit, blank, or null does not pass max_tokens. A positive int is forwarded. A non-positive int, bool, string, or float is rejected. |
| `options.provider` | deepseek-official | Provider id on initialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `deepseek-v4-flash` | Passed on `initialize`. |
| `api_key` | `DEEPSEEK_API_KEY` / `deepseek_api_key` / `litellm_api_key` | Env **locator name**. Projected as `DEEPSEEK_API_KEY`. Omit on loopback `base_url` (`127.0.0.1` / `localhost` / `::1`). |
| `base_url` | `DEEPSEEK_BASE_URL` / `deepseek_base_url` | Projected as `DEEPSEEK_BASE_URL`. Defaults to the official `https://api.deepseek.com`; no cross-provider fallbacks. |

## Install

```bash
uv tool install 'ageval-cli[dsh]'   # or: uv sync --extra dsh in this repo checkout
ageval plugin install plugins/dsh
ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.dsh.yaml --probe
```

Install updates `$AGEVAL_HOME/plugins` (default `~/.ageval/plugins`) only — **never**
edits `profiles.yaml` / `ageval.yaml` / `task.yaml`.

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: dsh
    extensions:
      - plugin: dsh
        options:
          composition: slim               # omit permission → unrestricted local bash/fs
          # permission: read-only         # or workspace-write | danger-full-access
      - plugin: docker
    model:
      id: deepseek-v4-flash
      reasoning:
        effort: xhigh
    api_key: ${deepseek_api_key}          # env locator
```

`options.permission` loads the sandboxed composition (`dsh-fs-sandbox` +
`dsh-sandbox-policy` + `dsh-sandbox-local`). GLM Coding Plan’s completion
window is 131072; the adapter default 256000 is rejected there — set
`max_tokens: 8192` (or another value in range) on that profile. Defaults
and rejected cases: Parameters above.

```yaml
        options:
          composition: slim
          max_tokens: 8192    # omit this key to keep the adapter default
```

The bundled `dsh-jsonrpc-agent` (`deepseek-harness-sdk==0.1.0rc6`) ships
`dsh-fs-sandbox` but **not** `dsh-bash-sandbox`. The sandboxed tree therefore
keeps `dsh-bash-local`. File-tool writes are fenced; a bash redirect can still
write. Do not claim bash confinement on this runtime.

Batch approval is `never` in the sandboxed tree so an unattended `ageval run`
cannot hang on a permission prompt. This is a DSH file-effect policy, not
ageval isolation. Docker + landlock / Seatbelt may fail to start
(`SANDBOX_UNAVAILABLE`); that fails immediately. Do not claim `isolated` from this
knob.

Same `run.py`; switch only via profiles or
`--set '/agent_profiles/<role>/options/permission="read-only"'`.

## minimal-demo smoke (real API)

```bash
ageval plugin install plugins/dsh
unset AGEVAL_OFFLINE_AGENT
ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.dsh.yaml
# file-effect policy (file-tool writes denied; bash can still write):
# ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
#   --profiles examples/datasets/minimal-demo/profiles.dsh.read-only.yaml
```

Evidence for a successful invoke includes worker metadata
`execution_location: attempt-container`. A kind that cannot `exec` fails at
`ageval lock`, not mid-invoke.

## Recognition ≠ this host can run ≠ image baked

- **install** → Recognition only (`plugin list` / executor visible)
- **`host_requires`** → local kind needs `deepseek_harness` on this interpreter (`uv tool install 'ageval-cli[dsh]'` / repo checkout `uv sync --extra dsh`); docker writes the wheels into the image
- **profiles `executor: dsh`** → this profiles file’s dsh executor (+ model / api_key locator)
- **`extensions: [{plugin: dsh}]`** → must be listed to write image layers / collect trajectory
- **`--probe`** → binding-aware feasibility; no Agent, no image write
- **image layers written** → `Dockerfile.bake` installs `deepseek-harness-sdk` into the image Python. The worker script is uploaded at invoke and run with `host.exec` + projected `DEEPSEEK_API_KEY`

Offline (`AGEVAL_OFFLINE_AGENT=1`) fails the check without calling the provider; the run does not start.
