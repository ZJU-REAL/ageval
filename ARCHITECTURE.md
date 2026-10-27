# ageval Architecture

This document specifies the **implementation structure** of `ageval`: current and target source layout, module ownership, dependency direction, composition root, Attempt lifecycle, cross-boundary data flow, failure/cleanup handling, and verification rules.

- Product and mechanism design authority: [docs/](docs/README.md) (especially [docs/design/](docs/design/)).
- Incremental delivery and acceptance tracking: [GitHub Issues](https://github.com/ZJU-REAL/ageval/issues).
- Reader-facing usage documentation: [website/](website/).

GitHub: [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval). The product name, packages, and CLI are **ageval**.

## Document Status

| Field | Value |
| --- | --- |
| Product | ageval (agent eval) |
| Implementation | Fixed Attempt phase pipeline; environment plugins `local` / `docker` / `e2b` / `ssh` / `daytona`; CLI entrypoints per `ageval --help` |
| Evidence grade | **`runnable-mvp`**: local ACP, docker ACP, and named `minimal-demo` tasks have verified public runs; `e2b`/`ssh`/`daytona` implementations exist and fail `--probe` when credentials are absent |
| Design authority | [docs/README.md](docs/README.md) |
| Structure authority | **This document** |
| Related design docs | [docs/PRD.md](docs/PRD.md), [docs/design/01](docs/design/01-core-lifecycle.md), [docs/design/04](docs/design/04-environments.md), [docs/design/05](docs/design/05-executors-and-acp.md) |
| Sync policy | See [Change Ownership](#change-ownership) |

Read **Current** and **Target** sections separately; do not treat unverified target items as shipped.

## System Overview

To decouple task logic from execution backends, `ageval` locks a **dataset** with a role **profiles** configuration, provisions an **environment** (bound to the `environment` exclusive slot), executes the task's `run.py` inside the Attempt lifecycle, and—after sealing solver sessions—runs an independent `evaluator.py` to produce and bind a structured `Result`.

Coding agents connect to the environment either through the parent-process **ACP** client over `host.attach_stdio` or through the external `acp-oneshot` executor (`host.exec` of an in-environment ACP client/server pair). Other harnesses and model endpoints bind to the per-profile `executor` exclusive slot via `ageval.plugin/1`.

### Main participants

| Participant | Owns | Does not own |
| --- | --- | --- |
| Operator / CLI | Invoking `lock` / `run` / `view`; reading exit codes and summaries | Task interaction logic, scoring criteria |
| Application | Use-case orchestration; **sole production composition root** | Duplicating domain or protocol rules |
| Config | `load_and_lock` → `LockedTaskConfig` + `extension_bindings` | Executing Python task workflows |
| Attempt engine | `run_attempt`: `environment → run → evaluate → record`, with `cleanup` in `finally` | Vendor SDKs, task interaction loops |
| Environment plugin | `preflight` / `start` / `exec` / `upload` / `download` / `attach_stdio` / `stop` | ACP protocol, `PASS` verdict |
| Capability layer | Authorized operation surface and quotas exposed to `run.py` | Issuing `PASS` verdicts |
| Evaluation | Phase boundary, subprocess `evaluator.py` runner, `bind_evaluation` | Task-specific scoring logic |
| SDK (`ageval_sdk`) | `RunContext`, `AgentSession`, local `ToolSet`, concurrency helpers | Run identity, host credentials, `PASS` verdict |
| Task `run.py` | Task interaction loop, domain tools, `ctx.params`, artifact registration | Container lifecycle, host credentials, `PASS` verdict |
| Plugins | Exclusive-slot and chain-slot implementations (`src/ageval/plugins/` + external `plugins/`) | Branching by benchmark name; bypassing registry resolution |
| Task `evaluator.py` | Task grading logic and `PASS` / `FAIL` status | Starting the solver agent, holding host secrets |

### End-to-end control flow

```text
dataset root (ageval.yaml / ageval.dataset/1)
  → resolve_task(--task) → tasks/<id>/task.yaml
  → merge profiles.yaml (environment + agent_profiles)
  → load_and_lock → ModelSpec contract check, LockedTaskConfig + extension_bindings + digest
  → IdentityFactory: Run / Trial / Attempt + evidence directory
  → host.preflight
  → run_attempt
       environment  host.start → upload data/ → after_environment_ready → environment_setup
       run          subprocess run.py ← Agent Service socket ← executor (attach_stdio / exec / HTTP)
       evaluate     seal solver sessions → [optional isolated scoring host(s)] → upload evaluation/ & artifact snapshots → subprocess evaluator.py → bind_evaluation
       record       trajectory_collect → trajectory_seal → summary_enrich
       finally      cleanup → stop started scoring host(s) + stop run environment
  → .ageval/runs/<attempt_id>/
```

## Runnable System Path

### Current (verified public commands)

| Item | Value |
| --- | --- |
| Public entrypoint | `ageval lock` / `run` (including `--probe`) / `replay` / `checkpoints` / `tasks` / `campaign` / `view` / `plugin` / `evidence` / `status` / `cancel` / `executors` / `jobs` / `results` / `publish` / `release` / `agent` / `registry` |
| Production composition root | `src/ageval/application/composition.py` |
| Smoke lock | `uv run ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg` (exit 0; summary has `dataset_id`) |
| Smoke docker ACP | `uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg` (default `minimal-demo` environment is `docker`) |
| Smoke local ACP | `uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00` (default environment is `local`; full run requires credentials + `tau2`) |
| Expected failure | Unknown format → `invalid_format` exit 2; `e2b`/`ssh`/`daytona` without credentials → `--probe` reports `ready: false` |
| Observable output | Secret-free lock summary + digest; Attempt directory contains `lock.json`, `result.json`, `trajectory.jsonl`, and `summary.json` |
| Evidence grade | **`runnable-mvp`** |

### Target — items not yet claimed as verified

| Item | Planned verification |
| --- | --- |
| Live ACP on `e2b` / `ssh` | Public `ageval run` with `environment: e2b` and `ssh` A/B using live credentials |
| External plugins live run | Verified `ageval run` for `nooa`, `dsh`, and `miniswe` |
| Named-example matrix | Full verification matrix in [docs/PRD.md](docs/PRD.md#6-in-repository-reference-examples-examples) |

## Source Layout

### Current Source Layout

```text
ageval/                              # GitHub: ZJU-REAL/ageval
├── AGENTS.md
├── ARCHITECTURE.md
├── README.md
├── pyproject.toml                   # name = "ageval-cli"; scripts ageval / ae
├── uv.lock
├── src/ageval/
│   ├── cli/                         # Typer: argv, help, exit code
│   ├── application/
│   │   ├── composition.py           # Sole production wiring; CLI imports build_* only from here
│   │   ├── lock.py                  # load_and_lock + capability/inject dependency graph
│   │   ├── run.py                   # mint identity → ctx → run_attempt
│   │   ├── regrade.py               # mint new Attempt → run_regrade (skips run phase)
│   │   ├── campaign.py
│   │   ├── suite/                   # suite_run, fingerprint, suite_metrics, summary document
│   │   ├── registry_ops/            # results / publish / login / org / list
│   │   ├── plugin_ops/
│   │   ├── agent_ops/               # --agent (+ optional --model) projected into profiles
│   │   ├── local_jobs/              # local Job list / get / delete
│   │   └── analysis/                # post-run stats / hack / review (read-only)
│   ├── attempt/                     # Single-Attempt execution pipeline
│   │   ├── __init__.py              # run_attempt phases; run_regrade skips run
│   │   ├── ctx.py
│   │   ├── emit.py                  # chain-slot next() dispatch
│   │   └── phases/
│   │       ├── environment.py
│   │       ├── run.py
│   │       ├── evaluate.py
│   │       ├── record.py
│   │       └── cleanup.py
│   ├── config/                      # dataset root + task.yaml + profiles resolution
│   ├── harbor/                      # built-in run/score for --layout harbor
│   ├── model/                       # ModelSpec · resolve_model
│   ├── environments/
│   │   ├── protocol.py              # EnvironmentProvider · StdioTransport · capabilities
│   │   └── streams.py
│   ├── plugins/
│   │   ├── base.py                  # BaseEnvironment · BaseExecutor
│   │   ├── decorators.py            # @environment_plugin / @executor_plugin
│   │   ├── slots.py                 # exclusive / chain slot identifiers
│   │   ├── registry.py / resolve.py / bootstrap.py / builtin.py
│   │   ├── defaults/                # environment_setup (setup.sh), default evaluation_runtime & trajectory_seal
│   │   └── contrib/
│   │       ├── acp/                 # ACP executor + attach_stdio client
│   │       ├── docker/              # Docker environment; attempt/ = official base image recipe
│   │       ├── local/
│   │       ├── e2b/
│   │       ├── daytona/
│   │       ├── ssh/                 # Mode A (remote host) / Mode B (remote container)
│   │       ├── openai_http/
│   │       └── anthropic_http/
│   ├── runtime/
│   │   ├── clocks.py                # Centralized CLOCKS table for default timeouts
│   │   ├── identity.py
│   │   ├── parent_agent.py          # Parent Agent Service + executor dispatch
│   │   ├── task_launch.py           # Subprocess launcher for run.py
│   │   └── task_worker.py
│   ├── evaluation/                  # Phase barrier + subprocess evaluator runner + bind_evaluation
│   ├── evidence/                    # Sole owner of .ageval/runs layout paths and trajectory sealing
│   ├── capabilities/
│   ├── registry/                    # Hub HTTP client
│   ├── viewer/                      # Local Viewer HTTP server (ageval packages and Harbor trees)
│   ├── control/
│   └── agents/                      # ageval.agent/1 cache + builtin catalog
│       ├── builtin/                 # catalog.json + shipped agent package trees
│       └── reserved.py              # Reserved builtin short IDs
├── src/ageval_sdk/                  # RunContext / RunTerminal / AgentSession
├── apps/
│   ├── shared/                      # Shared Hub + Viewer UI components and tokens
│   ├── viewer/                      # `ageval view` SPA
│   └── hub/                         # Registry Dataset / Plugin / Agent / Leaderboard SPA
├── services/registry/               # Standalone HTTP service: Route.access + *Service
│   ├── app.py / asgi.py / backend.py
│   ├── http/                        # Request dispatch + one handler module per aggregate
│   ├── auth/                        # AuthService, GitHub OAuth, token stores
│   ├── orgs/                        # Organization and user management
│   ├── packages/                    # Dataset, plugin, and agent package stores and catalogs
│   ├── runtimes/                    # Derived agent performance aggregation
│   ├── results/                     # Suite and Attempt result stores
│   ├── shares/                      # Read-only snapshot shares (static archive or live update)
│   ├── inbox/                       # Listing and performance attachment requests
│   ├── hosted/                      # Organization secrets + hosted job queue and worker
│   ├── content/                     # Package file indexing and BlobStore I/O
│   ├── db/                          # SQL dialect adapter and schema initialization (open_stores)
│   └── dataset.py / access.py / errors.py / paging.py / clock.py / envload.py / upload_slots.py / spool.py
├── examples/
│   ├── datasets/
│   │   ├── minimal-demo/            # terminal-jsonl-agg / tau2-dialog-min / multiagent-env-min
│   │   ├── concurrent-research/     # fanout concurrent-session example
│   │   ├── tau3-airline-5/          # airline-00 … airline-04
│   │   └── terminus-2-min/          # hello: host-loop tmux on docker
│   └── agents/                      # ageval.agent/1: dsh / nooa / miniswe / terminus-2 / openhands defaults
├── plugins/                         # External ageval.plugin/1 packages
│   ├── nooa/ / dsh/ / miniswe/ / terminus-2/ / openhands/ / acp-oneshot/
│   └── home-files/ / agent-skills/
├── tests/
├── docs/
└── website/
```

Hub Agent Performance is a **derived view** over public listed or consented `job_overlay.agent_ref` rows rather than a separate Core entity. Public Leaderboard listing is controlled by the Registry flag `board_listed` (distinct from package/result `visibility`). The `/leaderboard` plaza indexes Dataset Leaderboard, Agent Performance, and Model Performance via `GET /v1/results/suites?board=1` and `GET /v1/results/performances`.

During a production Attempt, `application/run.py` mints run identity once and invokes `attempt.run_attempt`. `application/regrade.py` mints a new Attempt and invokes `attempt.run_regrade`, which provisions the scoring environment and runs `evaluate` from archived artifact snapshots without executing `run.py`. Resource `cleanup` always runs in `finally`. The parent Agent Service and `limits` share a unified quota state: the service admits `run`-phase invocations, serializes calls within a single session in arrival order, and overlaps distinct sessions up to `limits.agent_concurrency` (default 1). At the end of `run`, `seal_run` cancels queued solver calls and drains in-flight solver executions before `mark_writers_stopped`. Evaluate-phase `judge` sessions execute serially without consuming solver invocation quotas.

### Generated artifacts (not source-edited)

| Path / pattern | Notes |
| --- | --- |
| `.ageval/` | Local runs, suite-runs, plugin cache, and credentials |
| `apps/shared/lib/evidence.gen.ts` | Generated from `evidence/documents.py` (`scripts/gen_evidence_ts.py --check`) |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | Python toolchain caches |
| `dist/`, `*.egg-info/` | Package build outputs |

## Module Ownership

| Path | Sole responsibility | Does not own |
| --- | --- | --- |
| `cli/` | CLI argument parsing, help text, exit codes | Task business logic, starting containers, constructing evidence paths |
| `application/` | Use-case orchestration (`lock`, `run`, `campaign`, `suite`, `registry`, `plugin`, `agent`, `jobs`, `analysis`) | Global mutable singletons outside bootstrap |
| `application/analysis/` | Post-run read-only `stats` / `hack` / `review` over sealed evidence | `PASS` verdicts, `checks.json`, Hub uploads |
| `application/composition.py` | Sole production `build_*` wiring | Task or scoring algorithms |
| `config/` | Dataset resolution, `task.yaml` / `profiles.yaml` validation, lock digest, Harbor `task.toml` intake | Executing `run.py` or `evaluator.py` |
| `harbor/` | Built-in Harbor instruction handoff and reward verdict | Environment lifecycle, docker CLI |
| `attempt/` | Fixed phase sequence, `emit` chain dispatch, `AttemptCtx` | Vendor SDKs, `container_id` |
| `environments/` | `EnvironmentProvider` protocol, capability flags, stdio stream types, `probe` / `attach` | Importing `e2b`, `docker`, or `paramiko` |
| `plugins/contrib/docker/` | `docker exec`, compose, UID/GID, image build; `attempt/` official base recipe | ACP protocol handling |
| `plugins/contrib/e2b/` | E2B SDK integration and template caching | Core-level template caching |
| `plugins/contrib/ssh/` | SSH Modes A and B (`ssh -T` / remote `docker exec`) | In-process fake agents |
| `plugins/contrib/acp/` | Parent ACP JSON-RPC client, entry registry, `attach_stdio` consumer | Writing `trajectory.jsonl` directly; scraping unstructured stdout |
| `plugins/defaults/` | `environment_setup` (`setup.sh`), default `evaluation_runtime` and `trajectory_seal` implementations | Issuing `PASS` directly |
| `runtime/` | Run identity, parent Agent Service, subprocess worker launchers, clocks/quotas | Environment plugin internals, scoring criteria |
| `evaluation/` | Phase barrier, subprocess evaluator execution, `bind_evaluation` | Task-specific scoring formulas |
| `evidence/` | Evidence directory layout, secret redaction, `activity.jsonl`, `replay-input.json`, `checkpoints/`, `trajectory.jsonl` sealing, document schemas | Vendor protocol parsing, `PASS` verdicts |
| `registry/` + `services/registry/` | Package and result HTTP client/server | Issuing `PASS`; exposing storage credentials to clients |
| `ageval_sdk` | Task-script types and session/tool helpers | Control-plane internals, `PASS` verdicts |
| `examples/` | Reference datasets and agent packages for smoke/regression checks | Full upstream benchmark distributions |
| `tests/` | Contract, unit, integration, and architecture tests | Production composition wiring |
| `docs/` | Product and mechanism design specifications | Task-tracking checklists |
| `website/` | Reader-facing bilingual documentation | Mechanism design authority |

## Dependency Direction

Arrows denote allowed Python import directions:

```text
cli ──────────────► application.composition
                         │
                         ├─► config / attempt / runtime / capabilities / evaluation
                         │
                         └─► plugins.bootstrap ──► plugins.builtin ──► contrib/* ──► environments.protocol
                                 (builtin imports explicit module tuples;
                                  protocol never imports contrib)

plugins.base ──► ageval.model · environments.protocol
ageval.model ──► (independent of plugins, contrib, and application)

ageval_sdk ──► public DTOs / protocol shapes only
               (never imports application, contrib internals, or private control-plane modules)
```

### Forbidden dependencies

- `environments/protocol.py` importing Typer, Docker SDK, E2B SDK, or SQLAlchemy.
- `cli/` invoking agent CLIs directly, constructing evidence paths, or bypassing `application.composition`.
- Control plane importing task `run.py` or `evaluator.py` as in-process Python modules.
- `ageval_sdk` reading host credential files, controlling Docker sockets, or binding `PASS`.
- Branching on benchmark names or task IDs inside Core or plugins.
- Referencing `container_id` or branching on `if kind == "e2b"` inside ACP, `attempt/`, or `run.py`.
- Hardcoding gateway-specific parameter lists inside `ModelSpec` or `resolve_model` (allowed `model.extra` keys belong on the executor's `extra_allowlist`).

## Composition Root

| Item | Rule |
| --- | --- |
| Sole production wiring point | `build_*` functions in `src/ageval/application/composition.py` |
| New public use case | Must expose a corresponding `build_*` function |
| CLI | Imports only `ageval.application.composition` (and `ageval.cli`) |
| Plugin discovery | `ExtensionRegistry` + `~/.ageval/plugins` local cache; missing plugins fail during `ageval lock` |

## Extension Emit Map

Core awaits registered chain-slot handlers and exclusive-slot implementations according to the locked dependency graph. Slot identifiers are defined in `src/ageval/plugins/slots.py`.

Exclusive slots: `environment`, `executor`, `evaluation_runtime`, `trajectory_seal`. `environment`, `evaluation_runtime`, and `trajectory_seal` bind once per Attempt, whereas `executor` binds one implementation **per role profile**. `evaluation_runtime` and `trajectory_seal` default to the engine (`plugin_id: default`). `PASS` enters `Result` exclusively through `bind_evaluation`.

```text
environment phase
  before_environment
  host.start
  upload data/ → /attempt/workspace
  after_environment_ready      # ACP runtime probe; skip install when baked version matches
  environment_setup            # run environment/setup.sh if present
  after_environment

run phase
  before_run
  subprocess python -m ageval.runtime.task_worker → run.py
    Agent.session → unix socket → ParentAgentService
      admit frame → serialize within session; overlap distinct sessions up to agent_concurrency
      reserve agent_invocations quota immediately before executor.invoke
      before/after_agent_open
      before_agent_invoke → profile executor.invoke → after_agent_invoke
      normalize_agent_result
      before/after_agent_close
  seal_run (cancel queued solver calls, drain in-flight solver calls)
  mark_writers_stopped (Agent Service remains open for evaluate-phase judge profiles)
  after_run

evaluate phase
  before_evaluate
  evaluation.collect           # optional: run collect commands and stage declared paths into verifier-collect/
  [evaluate_host.isolated, unnamed] start isolated Docker scoring environment (distinct work root)
  [unnamed] upload harvested artifacts, verifier-collect paths, and evaluation/ onto scoring host
  [isolated, unnamed] run after_environment_ready for evaluate-phase ACP profiles
  evaluation_runtime.evaluate  # default: subprocess evaluator.py worker
                               # named evaluation.environments: lazy start on first scoring.exec or session(environment=)
                               # optional: Agent.session(<judge>).invoke via ParentAgentService
                               # optional: write evaluation/checks.json from returned checks list
  bind_evaluation              # sole entry point for PASS / FAIL
  after_evaluate               # may attach metrics; cannot alter status

record phase
  trajectory_collect → trajectory_enrich
  trajectory_seal              # writes run-phase trajectory.jsonl
  evaluation/observation.jsonl # evaluate-phase judge trajectory (omits user prompts)
  summary_enrich               # populates Attempt summary.extra (omitted when empty)

cleanup (finally)
  cleanup_report
  stop started isolated scoring environment(s)
  host.stop
```

`FAIL_OPEN_SLOTS`: `before_run`, `after_run`, `trajectory_collect`, `trajectory_enrich`, `summary_enrich`, `cleanup_report`. Failures in any other slot fail the enclosing phase.

## Lifecycle

### Attempt state transitions

```text
created
  → locking          # load_and_lock
  → preflight        # host.preflight; missing credentials fail here
  → environment      # start + upload seed + setup
  → run              # run.py + bound executor(s)
  → evaluate         # seal solver + upload gold + evaluator.py + bind_evaluation
  → record           # seal trajectory and summary
  → cleanup          # finally block; runs on every exit path
  → terminal         # PASS | FAIL | ERROR
```

### Ordering invariants

1. No environment starts and no agent invocation occurs before `load_and_lock` succeeds.
2. `evaluator.py` never runs concurrently with an active solver session; reference materials (`evaluation/`) are uploaded only after solver writers are sealed.
3. `cleanup` runs on normal completion, timeout, cancellation, and exception paths; a cleanup warning never overwrites a bound evaluation result.
4. Every retry or regrade mints a **new Attempt** (`IdentityFactory.new_run` is called once per Attempt) without mutating previous Attempt directories.
5. `ageval campaign` expands parameter grid points across Trials without coupling to the internal control flow of `run.py`.

Detailed phase rules: [docs/design/01-core-lifecycle.md](docs/design/01-core-lifecycle.md).

## Data Flow

| Data | Producer | Consumer | Boundary rule |
| --- | --- | --- | --- |
| `ageval.yaml` + `task.yaml` + `profiles.yaml` | Author / CLI | Config | Sole specification reader; unknown format fails fast |
| `LockedTaskConfig` + `extension_bindings` | Config | Attempt, environment, executor, evaluation | Reproducible lock record; contains no plaintext secrets |
| `ctx.params` | Config projection | `run.py` | Read-only task parameters; excludes reference materials and secrets |
| Agent prompts / tool calls | `run.py` | Bound executor | Dispatched via ParentAgentService |
| Credential material | Host environment | Authorized executor subprocess | Referenced by env locator name; never written to lock or evidence |
| Workspace files | Environment upload | Agent and `run.py` | Mounted at `/attempt/workspace` |
| Harvested artifacts | `run.py` / workspace | `evaluate` phase | Snapshotted into `task-artifacts/` before grading |
| Evaluator return value | `evaluator.py` | `bind_evaluation` | Sole source of `PASS` or `FAIL` |
| `Result` (`result.json`) | Evaluation / Attempt | CLI, Viewer, Hub | Records `status`, `score`, `error`, `limit`, and `logs` |
| Evidence archive | `evidence/` | Operators, analyzers, `regrade` | Secret-redacted directory under `.ageval/runs/<attempt_id>/` |

## Platform Boundaries

| Capability / surface | Owner | Notes |
| --- | --- | --- |
| `environment: local` | `plugins/contrib/local` | Host directory workspace |
| `environment: docker` | `plugins/contrib/docker` | Container lifecycle, compose services, UID/GID, path views, and `network_mode: service:<name>` |
| `environment: e2b` | `plugins/contrib/e2b` | E2B SDK integration; missing `E2B_API_KEY` fails preflight |
| `environment: ssh` (A / B) | `plugins/contrib/ssh` | Mode A: remote host; Mode B: remote container |
| `environment: daytona` | `plugins/contrib/daytona` | Daytona snapshot/sandbox integration; missing `DAYTONA_API_KEY` fails preflight |
| ACP executor | `plugins/contrib/acp` | Parent JSON-RPC client over `attach_stdio` |
| Other executors | `openai-http`, `anthropic-http`, external `nooa`, `dsh`, `miniswe`, `terminus-2`, `openhands`, `acp-oneshot` | Uniform session interface via `BaseExecutor`. `terminus-2` keeps model HTTP on the parent and drives tmux with `environment.exec`. `openhands` runs the pinned SDK inside the attempt environment. Placement next to ACP and miniswe: [docs/design/05-executors-and-acp.md](docs/design/05-executors-and-acp.md#executor-placement) |
| Official Attempt image | `plugins/contrib/docker/attempt/` | Pulls `ghcr.io/zju-real/ageval-attempt:<cli-ver>` as `ageval-attempt:base` or builds from packaged Dockerfile |
| Registry HTTP service | `services/registry/` | Six aggregate stores (`packages`, `results`, `shares`, `orgs`, `inbox`, `hosted`) behind service classes; hosted worker runs `e2b` and `daytona` jobs ([docs/design/08](docs/design/08-hub-registry-and-agents.md#5-cloud-hosted-evaluation-jobs-servicesregistryhosted)) |

## Failure and Privacy Boundaries

When an Attempt terminates with `ERROR`, `result.json` records `error` as `{phase, title, message}`. `PASS` and `FAIL` leave `error` as `null` (including when `limit` records a `run`-phase quota such as `wall_time_seconds` or `agent_invocations`).

| Failure class | Outcome | Owner |
| --- | --- | --- |
| Config / schema / unknown format | Non-zero exit (`invalid_format`, `model_config`, etc.); run does not start | Config / CLI |
| Unsatisfied capability or `inject` dependency | `ageval lock` fails | Config / plugins |
| Missing credentials (`e2b` / `ssh` / `daytona` / ACP) | Preflight or invocation fails fast | Environment / executor |
| Run-phase quota reached (`wall_time_seconds`, `agent_invocations`) | `evaluator.py` still scores harvested artifacts (`PASS` or `FAIL`); `result.json` sets `limit` and leaves `error` `null` | Attempt |
| Environment phase timeout | `ERROR` (`phase: "environment"`, `title: "environment_timeout"`); `run` does not start | Attempt |
| Evaluate phase timeout | `ERROR` (`phase: "evaluate"`, `title: "evaluate_timeout"`) | Attempt |
| Evaluator status other than `PASS` / `FAIL` | `ERROR` (`phase: "evaluate"`, `title: "evaluator_invalid_status"`) | Evaluation |
| `evaluation.collect` command failure or missing path | `ERROR` (`phase: "evaluate"`, `title: "environment_collect_failed"` or `"environment_collect_missing"`) | Attempt |
| Evaluator crash or unhandled exception | `ERROR` (`phase: "evaluate"`, `title` set to exception class or `ScriptError.title`) | Evaluation |
| Cleanup failure | Logged as warning; does not overwrite a bound result | Environment / Attempt |

Privacy rule: API tokens, OAuth files, database passwords, and SSH private keys must never appear in `lock.json`, default stdout/stderr logs, or evidence archives.

## Change Ownership

Documentation does not need to be committed in a standalone initial commit before writing code. Instead, ensure the authoritative specification and downstream docs are updated when wrapping up a phase or completing the change:

| Change type | Authoritative doc | Sync when wrapping up the phase / PR |
| --- | --- | --- |
| Top-level directories, module ownership, import direction, composition root | **This document** (`ARCHITECTURE.md`) | Root `AGENTS.md`, code |
| Product or mechanism design, red lines, `EnvironmentProvider` protocol | `docs/design/*` (and `PRD.md` / `glossary.md` if needed) | Relevant sections here, `website/`, skills |
| Incremental delivery and acceptance tracking | GitHub Issues | PR description, smoke tests |
| User-facing CLI, Viewer, or Hub behavior | `website/` and `README.md` | CLI / service READMEs |

## Quick Index to Design Docs

| Topic | Document |
| --- | --- |
| Product overview, user stories US1-US12, and red lines | [docs/PRD.md](docs/PRD.md) |
| Core locking, phase lifecycle, `limits`, `upstream_stall`, and failure semantics | [docs/design/01](docs/design/01-core-lifecycle.md) |
| Dataset, `task.yaml`, `profiles.yaml`, `ModelSpec`, and `--layout harbor` | [docs/design/02](docs/design/02-schemas-and-config.md) |
| Task `run.py`, `ageval_sdk`, isolated evaluation (`evaluator.py`), and `gold` isolation | [docs/design/03](docs/design/03-task-sdk-and-evaluation.md) |
| `EnvironmentProvider`, `BaseEnvironment`, capabilities, and `local`/`docker`/`e2b`/`ssh`/`daytona` | [docs/design/04](docs/design/04-environments.md) |
| `BaseExecutor`, `ParentAgentService`, ACP, executor placement, and option tables | [docs/design/05](docs/design/05-executors-and-acp.md) |
| Declarative plugin slots, `ExtensionGraph`, and `export` / `inject` | [docs/design/06](docs/design/06-plugins-and-extensions.md) |
| Evidence archive, `trajectory.jsonl`, Suites, Campaigns, and read-only analyzers | [docs/design/07](docs/design/07-evidence-and-analysis.md) |
| Hub, Registry, Leaderboard Plaza, `ageval.agent/1` packages, and cloud-hosted jobs | [docs/design/08](docs/design/08-hub-registry-and-agents.md) |
| Web UI design system tokens and component invariants | [docs/design/09](docs/design/09-web-ui-design-system.md) |
