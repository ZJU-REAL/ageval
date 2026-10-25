# ageval Product Requirements Specification (PRD)

| Field | Value |
| --- | --- |
| Product Name | **ageval** (agent eval) |
| Delivery Unit | **dataset** (`ageval.dataset/1`) |
| CLI / Package | `ageval` (short alias: `ae`) / PyPI `ageval-cli` (`ageval` and `ageval_sdk`) |
| Home & Env Prefix | `~/.ageval` (`$AGEVAL_HOME`), `AGEVAL_*` |
| Normative Design Specs | [README.md](README.md) and [design/](design/README.md) (`01`-`09`) |
| Implementation Structure | [ARCHITECTURE.md](../ARCHITECTURE.md) |

---

## 1. Product Positioning and Problem Statement

### 1.1 Problem statement

Evaluating autonomous coding and tool-using agents across benchmarks typically suffers from three structural coupling problems:
1. **Harness and environment lock-in**: When task scripts directly invoke a specific vendor SDK or container CLI (`docker exec`), switching the evaluated agent runtime (harness) or moving execution from local containers to cloud sandboxes requires rewriting task code.
2. **Reference material (`gold`) leakage**: Mounting reference solutions or grading scripts into the workspace during agent execution allows capable coding agents to inspect test files or write directly to reward outputs.
3. **Unreproducible evaluation runs**: Without pre-execution configuration locking, explicit model parameter contracts (`ModelSpec`), and pre-effect resource quotas (`limits`), evaluation scores cannot be audited or compared reliably across teams.

### 1.2 Product solution

**ageval** decouples benchmark task logic from agent harnesses and execution environments by organizing every single-task execution as a strictly phased **Attempt**:
1. **Configuration Locking (`ageval lock`)**: Validates dataset manifests (`ageval.dataset/1`), task specifications (`ageval.task/1`), role bindings (`ageval.profiles/1` or `ageval.agent/1`), environment capabilities, and `ModelSpec` contracts before starting any environment, producing an immutable lock digest.
2. **Fixed Phase Pipeline (`ageval run`)**: Orchestrates `environment → run → evaluate → record` with `cleanup` guaranteed in `finally`.
3. **Isolated Grading (`evaluator.py`)**: Seals all solver sessions before uploading reference materials (`evaluation/`) into the scoring environment (or an isolated scoring container) and binds `PASS` or `FAIL` exclusively from `evaluator.py`.
4. **Secret-Redacted Evidence Archive**: Seals normalized trajectories (`trajectory.jsonl`), phase timings (`summary.json`), harvested workspace artifacts (`task-artifacts/`), and grading results (`result.json`) under `.ageval/runs/<attempt_id>/`.

---

## 2. Target Personas and Core Workflows

| Persona | Primary Responsibility | Key Entrypoints and Surfaces |
| --- | --- | --- |
| **Benchmark Author / Converter** | Package tasks with `task.yaml`, `run.py`, `evaluator.py`, `data/`, `evaluation/`, and optional `environment/Dockerfile` without managing container lifecycles or host credentials. | `ageval lock`, `ageval prepare`, `ageval publish` |
| **Plugin Author** | Extend `environment` or `executor` exclusive slots and lifecycle chain slots by protocol or execution mechanism (`acp`, `docker`, `e2b`, `daytona`, `ssh`, `openai-http`, `miniswe`, `terminus-2`, `openhands`). | `BaseEnvironment`, `BaseExecutor`, `ageval plugin` |
| **Evaluation Operator** | Run single tasks, full dataset suites, or parameter campaigns across different agents, models, and environments using CLI flags or hosted jobs. | `ageval run`, `ageval campaign`, `--agent`, `--model`, `--resume-suite` |
| **Result Analyzer / Reviewer** | Inspect sealed trajectories, run read-only post-run analyzers (`stats`, `hack`, `review`), regrade archived artifacts (`regrade`), and curate public Leaderboards on Hub. | `ageval view`, `ageval results analyze`, `ageval results regrade`, Hub SPA |

---

## 3. Architectural Layer Responsibilities

| Layer | Owns | Must Never Own |
| --- | --- | --- |
| **Core (`config`, `attempt`, `runtime`, `evaluation`, `evidence`)** | `load_and_lock` resolution; Attempt identity and phase pipeline; `EnvironmentProvider` protocol; `limits` enforcement; solver sealing; `gold` upload and `bind_evaluation`; evidence redaction and sealing. | Vendor-specific SDKs in Core protocols; task interaction loops; task-specific grading formulas. |
| **Plugins (`plugins/contrib/*`, external `plugins/*`)** | Concrete `environment` and `executor` exclusive-slot implementations and chain-slot hooks, registered via `@environment_plugin` / `@executor_plugin`. | Branching on benchmark names or task IDs; bypassing `ExtensionRegistry`; issuing `PASS` verdicts. |
| **Python SDK (`ageval_sdk`)** | Task-script helper types (`RunContext`, `Agent`, `AgentSession`, `ToolSet`, `bounded_gather`, `first_success`, `evaluation_check`). | Minting Attempt identity; reading host credentials; starting/stopping containers; deciding `PASS`. |
| **Dataset Tasks (`tasks/<id>/*`)** | Task interaction loop (`run.py`), domain tools, artifact publication, environment recipe (`environment/`), and grading logic (`evaluator.py`). | Duplicating Attempt phase orchestration; reading `evaluation/` during `run`. |
| **Application & Services (`application/`, `cli/`, `services/registry/`)** | Composition root (`build_*`), CLI argument parsing, Suite and Campaign orchestration, local Viewer server, and Hub Registry/Leaderboard service. | Executing task modules in-process; exposing storage or org secrets in API responses. |

---

## 4. Normative User Stories (US1-US12)

### US1 — Switch environments via configuration only
`ageval run` selects the execution backend (`local`, `docker`, `e2b`, `ssh`, `daytona`) solely from `environment:` in `profiles.yaml` without modifying `run_attempt`, `run.py`, or `evaluator.py`. Missing cloud sandbox or SSH credentials fail fast during `preflight` (or `--probe`).

### US2 — Reuse a single `Dockerfile` across local and cloud environments
A task's `environment/Dockerfile` (or `docker_image`) builds a local image under `environment: docker`, an E2B template under `environment: e2b`, and a Daytona snapshot under `environment: daytona`. If a task requires a capability (such as `compose`) that the selected environment does not provide, `ageval lock` rejects the configuration before execution.

### US3 — Run `setup.sh` at the end of the `environment` phase
When `tasks/<id>/environment/setup.sh` exists, Core executes it via `host.exec` in the `environment_setup` chain slot at the end of the `environment` phase. Non-zero exit codes fail the Attempt with `ERROR` (`phase: "environment"`, `title: "environment_setup_failed"`) without polluting the agent trajectory. Heavy system packages belong in `environment/Dockerfile`.

### US4 — Connect ACP coding agents uniformly across environments
`executor: acp` declares `inject: [service: environment, capabilities: [attach_stdio]]` and communicates over the bidirectional stream returned by `host.attach_stdio(argv, placement=placement, env=child_env)`. `Placement` never exposes `container_id` or vendor handles, and the ACP plugin never imports `docker`, `e2b`, `daytona`, or `ssh` modules.

### US5 — Enforce environment capabilities statically during `lock`
`task.yaml` `requires.environment` defaults to empty; when non-empty, `ageval lock` verifies `requires.environment ⊆ host.capabilities` and fails fast with `capability_missing` if any required capability is unsupported.

### US6 — Manage multi-container sidecars via Compose and `service=`
Auxiliary services (such as PostgreSQL or Redis) are declared in `environment/compose.yaml` (or `docker-compose.yaml`) and accessed via `host.exec(..., service=<name>)` or over the Compose project network (where the Attempt container joins as hostname `main`).

### US7 — Add new environment or executor plugins without touching Core
A new environment backend or agent executor is added by subclassing `BaseEnvironment` or `BaseExecutor`, registering with `@environment_plugin` or `@executor_plugin`, and shipping `plugin.yaml`, requiring zero changes to `attempt/`, ACP, or task scripts.

### US8 — Encapsulate image and template caching inside environment plugins
Recipe hashing, Docker image tag caching, E2B template caching, and Daytona snapshot caching are encapsulated entirely inside their respective environment plugins; Core invokes only `await ctx.host.start(force_build=ctx.lock.force_build)`.

### US9 — Keep the top-level phase pipeline directly inspectable
Opening `src/ageval/attempt/__init__.py` and `src/ageval/attempt/phases/*.py` reveals the entire Attempt phase sequence and emitted chain slots in one place.

### US10 — Auto-detect conventional task files
Task authors provide `run.py`, `evaluator.py`, `data/`, `evaluation/`, and optional `environment/Dockerfile` or `environment/setup.sh` without repeating default filenames in `task.yaml` ([design/02-schemas-and-config.md](design/02-schemas-and-config.md)).

### US11 — Delay reference material (`gold`) upload until `evaluate`
`tasks/<id>/evaluation/` is never mounted or uploaded during `environment` or `run`. Only after `seal_run` stops solver writers does `evaluate` upload `evaluation/` to the scoring host (or to an isolated scoring container when `evaluate_host.isolated: true`).

### US12 — Support SSH remote environments and pre-run ACP runtime probing
`environment: ssh` supports Mode A (remote host directory via `ssh -T`) and Mode B (remote container via `ssh -- docker exec -i`). During `after_environment_ready`, the ACP hook verifies the Node.js version floor (`runtime.node`), global npm package versions (`npm ls -g --depth=0`), binary `realpath`, and an ACP stdio `initialize` handshake; on a version miss it runs the pinned `install_command` once and re-probes, failing the `environment` phase if still unsatisfied.

---

## 5. Architectural Red Lines and Non-Goals

1. **Verdict exclusivity**: `PASS` and `FAIL` come solely from `evaluator.py` bound via `bind_evaluation` in `evaluate`. `RunTerminal.completed`, trajectory presence, or ACP `end_turn` never imply `PASS`.
2. **Credential locator safety**: Plaintext API keys, OAuth tokens, and SSH private keys MUST NEVER enter `lock.json`, `result.json`, `trajectory.jsonl`, `summary.json`, or default logs. Configs store only environment variable names (locators).
3. **Mechanism-based naming**: Plugins and adapters are named after protocols or execution mechanisms (`acp`, `docker`, `e2b`, `daytona`, `ssh`, `openai-http`, `anthropic-http`, `miniswe`, `terminus-2`, `openhands`, `dsh`, `nooa`), never after benchmarks.
4. **Strict locality**: `docker exec` stays inside `plugins/contrib/docker/`. ACP, `attempt/`, and `run.py` never reference `container_id` or branch on `if kind == "e2b"`.
5. **Gold isolation**: `/attempt/evaluation` does not exist in the solver environment during `environment` or `run`.
6. **No legacy format shims**: Unknown `format` values fail immediately with `invalid_format` at `/format`.
7. **No mock executors**: There is no product `executor: mock`, and mocked environments or stubbed agents do not count as acceptance evidence.
8. **Unconditional cleanup**: `cleanup` always runs inside `try/finally`. Plugins cannot bypass `cleanup` or issue `PASS`.
9. **Single composition root**: Production wiring lives exclusively in `build_*` functions in `src/ageval/application/composition.py`; `cli/` imports only `composition`.
10. **Single identity mint per Attempt**: `IdentityFactory.new_run` is called once per Attempt; settled Attempt directories are never overwritten in place.
11. **Static dependency verification**: Plugin `inject` service and capability requirements are verified during `ageval lock` before any environment starts.

---

## 6. In-Repository Reference Examples (`examples/`)

The repository maintains lightweight reference datasets and agent packages under `examples/` for smoke verification and regression checks (full-scale upstream benchmark conversions are distributed via Hub):

| Path | Contents and Verification Target |
| --- | --- |
| `examples/datasets/minimal-demo` | `terminal-jsonl-agg`, `tau2-dialog-min`, `multiagent-env-min` (default `environment: docker` with ACP `entry: pi`, plus alternate profiles for `nooa`, `dsh`, `openhands`, and `e2b`). |
| `examples/datasets/concurrent-research` | `fanout` (multi-session concurrency within a single Attempt via `bounded_gather`). |
| `examples/datasets/tau3-airline-5` | `airline-00` ... `airline-04` (5-task converted subset of the $\tau^3$-bench airline domain). |
| `examples/datasets/terminus-2-min` | `hello` (parent-loop `terminus-2` driving an in-container `tmux` session on `docker`). |
| `examples/agents` | `dsh-default`, `nooa-default`, `miniswe-default`, `terminus-2-default`, `openhands-default` (`ageval.agent/1` packages for external executors). |
