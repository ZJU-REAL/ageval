# 02 — Schemas, Configuration Locking, and `ModelSpec`

This specification defines the normative schemas and resolution rules for **dataset** manifests (`ageval.yaml`), member **task** manifests (`tasks/<id>/task.yaml`), **profiles** configurations (`profiles.yaml`), **`ModelSpec`** contracts, dataset-level asset preparation (`assets` and `prepare`), git-backed dataset sources, and `--layout harbor` intake.

Implementation modules live in `src/ageval/config/` (`dataset.py`, `profiles.py`, `load_and_lock.py`, `validate.py`, `digest.py`) and `src/ageval/model/`.

---

## 1. Scope and Configuration Invariants

1. **Strict format check**: Every manifest MUST declare its `format` string (`ageval.dataset/1`, `ageval.task/1`, `ageval.profiles/1`, `ageval.plugin/1`, `ageval.agent/1`). Any unrecognized `format` fails immediately at `/format` with `invalid_format` (exit code `2`).
2. **Task ID matches directory name**: Each member task resides at `<dataset_root>/tasks/<id>/task.yaml`, where the directory name `<id>` MUST equal `task_id` and the `--task <id>` CLI argument.
3. **Secret-free manifests and lock**: `api_key` fields in `profiles.yaml` accept only environment variable locator references (such as `${ZHIPU_API_KEY}` or `OPENAI_API_KEY`). Plaintext credentials and URLs containing userinfo (`https://user:pass@host`) are rejected during validation.
4. **Immutable limits under `--set`**: `--set` overrides are restricted to an explicit path allowlist; `limits.*` cannot be modified via `--set`.
5. **No implicit layout guessing**: Native `ageval.dataset/1` trees and Harbor trees (`--layout harbor`) are strictly separated. Passing `--layout harbor` on a directory containing `ageval.yaml` or `task.yaml` fails fast with `harbor_layout_mix`.

---

## 2. Root Dataset Manifest (`ageval.yaml` — `ageval.dataset/1`)

```yaml
format: ageval.dataset/1
dataset_id: example/minimal-demo
version: "0.1.0"
description: "Minimal reference tasks for smoke verification."
tasks:
  root: tasks
assets:
  - path: tasks/clip-01/data/clip.mp4   # Relative to dataset root; ".." is forbidden
    url: https://cdn.example.com/clip-01.mp4
    sha256: <64-hex-chars>
prepare: ./prepare.sh                    # Optional dataset-level preparation script
```

### 2.1 Dataset source resolution (`local`, Hub reference, and `git` source)

The first positional argument to `ageval lock`, `ageval run`, `ageval view`, and `ageval results upload-suite` accepts three source forms (`ageval tasks` and `ageval campaign` accept local directory paths only):

| Source Form | Syntax Example | Resolution Rules |
| --- | --- | --- |
| **Local path** | `examples/datasets/minimal-demo` | Resolves directly on disk. Passing `--dir` with a local path fails with `invalid_override`. |
| **Hub package ref** | `official/demo@0.1.0` or `official/demo@sha256:...` | Uses verified local cache when present; on `ageval run --dir <path>`, materializes into `<path>/<dataset_id>/` (reusing an existing matching checkout). |
| **Pinned git ref** | `github:org/repo@<tag\|full-sha>[#<subdir>]` or `https://...@<tag\|full-sha>[#<subdir>]` | Resolves the ref to a full 40-char commit SHA, performs a partial + sparse checkout (falling back to full fetch if unsupported by the remote) into the local git cache keyed by `(git_url, commit, subdir)`, and records `source.git_url`, `source.commit`, `source.subdir`, and `eval_digest` in the lock. Unpinned refs (missing `@` or pointing to a branch name), symlinks escaping the dataset root, or URLs containing userinfo fail with `invalid_package`. |

### 2.2 Dataset-level `assets` and `prepare`

`ageval prepare <dataset>` (also invoked automatically before `ageval lock` and `ageval run` on native datasets) executes between dataset resolution and Attempt creation:

1. **`assets` download and verification**: For each entry in `assets`, if `<dataset_root>/<path>` already exists with a matching `sha256`, download is skipped; otherwise the file is downloaded, verified against `sha256`, and written atomically. Download failure raises `asset_download_failed`; digest mismatch raises `asset_digest_mismatch`.
2. **`prepare` script execution**: Disabled by default. The script runs only when `--allow-prepare` is passed or the dataset matches `AGEVAL_PREPARE_TRUST` (comma-separated `dataset_id` or root paths); otherwise it fails with `prepare_not_allowed`. When authorized, it runs with `cwd = dataset_root` as the invoking user under a `600`-second default timeout, and all declared `assets` are re-verified afterward (failure raises `prepare_failed`). Completion is cached in `.ageval-prepare.json` keyed by the hash of `(prepare script content + assets manifest)` so a suite runs it at most once.
3. **`eval_digest` inclusion**: Downloaded asset bytes are excluded from `eval_digest` because the manifest already pins `path + sha256`; the `prepare` script content itself is included in `eval_digest` ([08-hub-registry-and-agents.md](08-hub-registry-and-agents.md)).

---

## 3. Member Task Manifest (`tasks/<id>/task.yaml` — `ageval.task/1`)

```yaml
format: ageval.task/1
task_id: terminal-jsonl-agg
parameters:
  instruction: "Aggregate events.jsonl into aggregates.json."
  cpus: 2
  memory_mb: 4096
agent_profiles:
  - id: solver
requires:
  environment: []              # Subset of EnvironmentCapabilities; verified at lock time
limits:
  wall_time_seconds: 600       # Run phase budget; default 300
  environment_seconds: 600     # Environment phase budget; default 600
  evaluate_seconds: 600        # Evaluate phase budget; default 600
  agent_invocations: 1         # Run-phase model invocation ceiling
  agent_concurrency: 1         # Max concurrent running run-phase invokes; default 1
artifacts:
  publishable:
    - id: reply
      path: artifacts/reply.json
      kind: file               # "file" (default) or "tree"
evaluation:
  inputs:
    - artifact: reply
      target: artifacts/reply.json
```

### 3.1 Conventional task directory layout and auto-detection

```text
tasks/<id>/
├── task.yaml                   # Required manifest; directory name <id> == task_id
├── run.py                      # Auto-detected as run:run (executed in run phase)
├── evaluator.py                # Auto-detected as evaluator:evaluate (executed in evaluate phase)
├── environment/
│   ├── Dockerfile              # Solver environment recipe (shared by docker, e2b, daytona)
│   ├── compose.yaml            # Optional auxiliary service topology (docker only)
│   ├── evaluate.Dockerfile     # Single isolated scoring container recipe
│   ├── evaluate/<name>/Dockerfile  # Named scoring container recipes
│   └── setup.sh                # Executed in environment_setup chain slot if present
├── data/                       # Uploaded to /attempt/workspace during environment phase
└── evaluation/                 # Reference materials (gold); uploaded only during evaluate phase
```

| Omitted YAML Field | Auto-Detection Rule |
| --- | --- |
| `run` entrypoint | If `run.py` exists → binds `run:run`. |
| `evaluator` entrypoint | If `evaluator.py` exists → binds `evaluator:evaluate`. |
| Solver environment recipe | If `environment/Dockerfile` exists → used automatically unless overridden by `environment_options.image` / `docker_image`. |
| Scoring container recipe | If `environment/evaluate.Dockerfile` (or `evaluation.docker_image`) exists → used when `evaluate_host.isolated: true` and `evaluation.environments` is omitted. Ignored when `evaluate_host` is omitted. |
| Setup script | If `environment/setup.sh` exists → executed in `environment_setup`; skipped when absent. |
| `requires.environment` | Defaults to `[]`. |
| Seed data (`data/`) | Uploaded to `/attempt/workspace` in `environment` phase if directory exists. |
| Reference materials (`evaluation/`) | Uploaded to scoring host in `evaluate` phase if directory exists. |

---

## 4. Profiles Configuration (`profiles.yaml` — `ageval.profiles/1`) and `ModelSpec`

```yaml
format: ageval.profiles/1
environment: docker             # local | docker | e2b | ssh | daytona
environment_options:
  network: bridge
  egress: llm
  egress_allow:
    - api.example.com
evaluate_host:
  isolated: true
  environment_options:
    network: none
agent_profiles:
  solver:
    executor: acp
    model:
      id: openai/example-model
      api: responses
      reasoning:
        effort: xhigh
      timeout: 120
      watchdog: 300
      extra:
        reasoning:
          summary: auto
    api_key: ${OPENAI_API_KEY}
    options:
      entry: codex
    extensions:
      - plugin: acp
      - plugin: docker
```

### 4.1 `ModelSpec` schema and resolution rules (`src/ageval/model/`)

To configure model parameters independently of the agent harness and prevent silent protocol fallbacks from altering experimental conditions, every role profile's `model` block resolves into an immutable **`ModelSpec`** via `resolve_model(model, options=None)`. Passing a bare string `model` or placing flat model keys (`api`, `reasoning_effort`, `timeout`, `request_timeout`, `watchdog`, `extra_body`) inside `options` fails immediately with `ModelConfigError` (`kind="model_config"`).

| YAML Path under `model:` | `ModelSpec` Attribute | Type | Default / Behavior When Omitted |
| --- | --- | --- | --- |
| `id` | `id` | `str` | **Required** (empty or whitespace-only strings are rejected). |
| `api` | `api` | `str` | Defaults to `"chat"`; only `"chat"` and `"responses"` are valid. |
| `reasoning.effort` | `reasoning_effort` | `str \| None` | Remains `None` (omitted from wire payloads). |
| `timeout` | `timeout` | `float \| None` | Remains `None` (executors fall back to `180` seconds from `src/ageval/runtime/clocks.py`; `0`, negative, or non-finite values are rejected). |
| `watchdog` | `watchdog` | `float \| None` | Remains `None` (executors fall back to `180` seconds from `clocks.py`; `0`, negative, or non-finite values are rejected). |
| `extra` | `extra` | `Mapping[str, Any]` | Defaults to `{}`. |

1. **`reasoning.effort` encoding and `"max"` alias**:
   - Omitted `reasoning.effort` is never sent on the wire; explicit `reasoning.effort: none` is sent verbatim as `"none"`.
   - Chat Completions (`api: chat`) encodes top-level `reasoning_effort`, whereas Responses (`api: responses`) encodes nested `reasoning.effort`.
   - When set to `"max"`, `ageval lock` resolves the profile's `model.id` against the canonical models catalog ([08-hub-registry-and-agents.md](08-hub-registry-and-agents.md)) and substitutes the highest tier from that model's `reasoning_options` list into the locked configuration; if the model cannot be uniquely joined or declares no `reasoning_options`, `lock` fails fast.
2. **`extra` and `extra_allowlist`**:
   - `extra` passes vendor-specific parameters (such as `reasoning.summary`, `thinking`, or `provider`) and MUST NOT shadow first-class keys (`id`, `api`, `timeout`, `watchdog`, `reasoning_effort`, or `extra.reasoning.effort`).
   - Every `BaseExecutor` subclass explicitly declares `extra_allowlist: frozenset[str]` on the class body (`frozenset()` rejects all `extra` keys). `BaseExecutor.supports_model(spec)` verifies `supported_apis`, `supported_model_fields`, and `extra_allowlist` statically during `ageval lock` ([05-executors-and-acp.md](05-executors-and-acp.md)).

### 4.2 `--set` override allowlist

`--set <pointer>=<value>` may modify only the following canonical JSON Pointer paths:
- `/parameters/seed`
- `/parameters/active_profile`
- `/agent_profiles/<role>/model` (nested object) or `/agent_profiles/<role>/model/{id,api,timeout,watchdog}` and `/agent_profiles/<role>/model/reasoning/effort`
- `/agent_profiles/<role>/{executor,api_key,base_url}`
- `/agent_profiles/<role>/options/<key>`

Attempting to override `limits.*` or any unlisted path fails fast during `ageval lock`.

---

## 5. Harbor Layout Intake (`--layout harbor`)

When `--layout harbor` is passed explicitly on `ageval lock` or `ageval run`, Core ingests unmodified Harbor task directories without requiring `ageval.yaml` or `task.yaml`:

1. **Accepted directory shapes**:
   - **Single Harbor task**: Directory contains `task.toml`, `instruction.md`, `tests/test.sh`, and `environment/` (or `environment.docker_image`). Passing `--task` in this shape is rejected.
   - **Harbor task collection**: Parent directory whose direct subdirectories are Harbor tasks. Omitting `--task` runs the full suite; `--task <id>` filters by directory name. If `[task].name` is present in `task.toml` and differs from the directory name, locking fails.
   - A root Harbor `registry.json` index is rejected (`harbor_registry_rejected`).
2. **Viewer auto-detection**: `ageval view <path>` opens a Harbor task or collection directory directly (and lists `.ageval/suite-runs` under that root) without requiring `--layout harbor`.
3. **`task.toml` field mapping**:

| Harbor `task.toml` Field | Mapped ageval Contract |
| --- | --- |
| `agent.timeout_sec` (when present) | `limits.wall_time_seconds` (never inherits `verifier.timeout_sec`) |
| `verifier.timeout_sec` | `limits.evaluate_seconds` |
| `environment.build_timeout_sec` | `limits.environment_seconds` |
| `cpus`, `memory_mb`, `gpus`, `gpu_types` | `parameters.*` (enforced by `docker` host on `start`) |
| `network_mode` (`"public"` \| `"no-network"`) / `allow_internet` | Container network mode. `allowlist` or per-phase network overrides fail with `harbor_network_unsupported`. |
| `user` | Numeric UID only; username strings are rejected. |
| `[[verifier.collect]]` + top-level `artifacts` | `evaluation.collect` (runs commands first, then copies absolute paths). |
| `storage_mb`, verifier CPU/mem, `skills_dir`, `solution.env` | Recorded in `parameters.harbor_known_gaps` (observational; not silently faked). |
| `steps`, Windows, MCP, healthcheck, TPU | Rejected during `lock`. |

4. **Built-in Harbor runner and `--oracle`**:
   - Without `--oracle`, the built-in runner passes the full text of `instruction.md` to role profile `solver` in a single `invoke` call (bound via `agent_profiles.solver` or wildcard `*`; missing binding fails lock with `missing_binding`), and `solution/` is excluded from the workspace and grading path.
   - With `--oracle`, the runner executes `solution/solve.sh` during the `environment` phase instead of invoking the solver agent.
