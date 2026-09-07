# ageval Architecture

This document maintains **implementation structure** only: current vs target layout, module ownership, dependency direction, composition root, run lifecycle, cross-boundary data flow, failure/cleanup ownership, evidence grades, and change sync.

- Do **not** write product essays, version checklists, or Phase task tables.
- Product and mechanism design authority: [docs/](docs/README.md) (especially [docs/design/](docs/design/)). **Self-contained**; do not read an out-of-repo BRIEF.
- Incremental delivery and acceptance tracking: [GitHub Issues](https://github.com/ZJU-REAL/ageval/issues).
- Reader-facing docs: [website/](website/) (not design authority).

GitHub: [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval). The product name, packages, and CLI are **ageval**.

## Document Status

| Field | Value |
| --- | --- |
| Product | ageval (agent eval) |
| Implementation | Attempt five-phase pipeline is wired; box kinds `local` / `docker` / `e2b` / `ssh` / `daytona`; public commands follow `ageval --help` |
| Evidence grade | **Limited to `runnable-mvp`**: local ACP, docker ACP, and named `minimal-demo` tasks have public runs. e2b/ssh/daytona **code exists; skip without keys — do not mark isolated** |
| Design authority | [docs/README.md](docs/README.md) |
| Structure authority | **This document** |
| Near-term target structure | [docs/design/00](docs/design/00-overview-and-product.md), [docs/design/01](docs/design/01-ageval-core.md), [docs/design/09](docs/design/09-owner-matrix-and-structure.md) |
| Update trigger | See [Change Ownership](#change-ownership) at the end |

**Do not** treat the Target tree or diagrams below as “already shipped.” Read Current and Target separately.

## System Overview

ageval locks a **dataset**, opens a **box** (exclusive slot `environment`), runs the task `run.py` on a visible Attempt pipeline, then — after writers stop — an independent `evaluator.py` scores and binds a flat Result.

Coding agents enter the box through the parent **ACP** client + `host.attach_stdio`, or through the external `acp-oneshot` executor (`host.exec` of an in-environment ACP pair). Other execution mechanisms fill the exclusive slot `executor` via `ageval.plugin/1`.

### Main participants

| Participant | Owns | Does not own |
| --- | --- | --- |
| Operator / CLI | Start lock/run/inspect; read exit code and summary | Business workflow, scoring algorithm |
| Application | Use-case orchestration; **sole composition root** | A second copy of framework-agnostic domain rules |
| Config | `load_and_lock` → `LockedTaskConfig` + `extension_bindings` | Interpreting the Python workflow |
| Attempt host | `run_attempt`: environment → run → evaluate → record; `finally` cleanup | Vendor SDKs, the task loop |
| Box (environment winner) | `preflight` / `start` / `exec` / `upload` / `download` / `attach_stdio` / `stop` | ACP protocol, PASS |
| Capability | Authorized operation surface exposed to `run.py` | Issuing final PASS |
| Evaluation | Barrier, in-environment evaluator, `bind_evaluation`, evidence | Unifying every scoring algorithm |
| SDK (`ageval_sdk`) | `RunContext`, `AgentSession`, Tool soft limits | Run identity, credentials, verdict |
| Task `run.py` | Business loop, local Tools, `ctx.params` | Docker, credentials, final PASS |
| Plugins | Exclusive / chain slot implementations; `src/ageval/plugins/` registry + first-party contrib | Branching by Benchmark name; a second resolve path |
| Evaluator (package) | Task truth | Starting the Agent, holding host secrets |

### Target data/control main flow (validated-output direction)

```text
dataset root (ageval.yaml / ageval.dataset/1)
  → resolve_task(--task) → tasks/<id>/task.yaml
  → merge profiles.yaml (environment + agent_profiles)
  → load_and_lock → LockedTaskConfig + extension_bindings + digest
  → IdentityFactory: Run / Trial / Attempt + evidence root
  → host.preflight
  → run_attempt
       environment  host.start → upload data/ → after_environment_ready → environment_setup
       run          subprocess run.py ← Agent Service socket ← attach_stdio
       evaluate     solver writers stopped → [opt-in scoring host(s)] → gold/snapshot on started host(s) → parent evaluator.py (Agent Service; optional scoring.exec) → bind
       record       trajectory_collect → trajectory_seal → summary_enrich
       finally      cleanup → each started evaluate_host.stop + host.stop
  → .ageval/runs/<attempt_id>/
```

Arrows mean **control-flow progress**. Cross-trust-boundary data flow is in [Data Flow](#data-flow-current).

## Runnable System Path

### Current (verified public commands)

| Item | Value |
| --- | --- |
| Public entrypoint | `ageval lock` / `run` (including `--probe`) / `tasks` / `campaign` / `view` / `plugin` / `evidence` / `status` / `cancel` / `executors` / `jobs` / `results` / `publish` / `release` / `agent` / `registry` (CLI is authoritative) |
| Production composition root | `src/ageval/application/composition.py` |
| Smoke lock | `uv run ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg` (exit 0; summary has `dataset_id`, no `database_id`) |
| Smoke docker ACP | `uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg` (default `minimal-demo` box is docker) |
| Smoke local ACP | `uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00` (default box is local; run needs credentials + tau2) |
| Smoke demo | `uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg`; `… --task tau2-dialog-min` |
| Expected failure | Unknown format → `invalid_format` exit 2; missing `--task` follows CLI; e2b/ssh/daytona without keys `--probe` `ready:false` |
| Observable result | Secret-free lock summary + digest; Attempt has `lock.json` / `result.json` / `trajectory.jsonl` |
| Evidence grade | **Limited to `runnable-mvp`** (commands above; do not upgrade from documentation) |

Suggested check after doc edits:

```bash
git diff --check
# when website/ changes: pnpm --dir website build
```

### Target — structure/evidence not claimed done

| Item | Planned value |
| --- | --- |
| Real ACP on e2b / ssh | Same task, public `ageval run` with `environment: e2b` and ssh A+B (tick only with credentials). Skip without keys ≠ pass. The Protocol seam needs a second real cloud winner |
| External plugins actually run | One real `ageval run` each for nooa / dsh; miniswe at least lock. install recognition ≠ a real run |
| Tree check | Do not keep two of `plugins/defaults` and `contrib/defaults`; CLI imports composition only |
| Named-example hard cut | lock/run listed in [docs/design/10](docs/design/10-examples-database-52.md); leftover old formats in-tree must fail lock |
| Docs | This document’s Current = `src/ageval` + five phases |

Earlier intermediate checkpoints follow code and examples. **Do not** treat Target as Current.

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
│   │   ├── composition.py           # CLI imports builders only from here
│   │   ├── lock.py                  # load_and_lock + capability/inject graph
│   │   ├── run.py                   # mint identity → ctx → run_attempt
│   │   ├── campaign.py
│   │   ├── suite/                   # suite_run, fingerprint, suite_metrics, summary document
│   │   ├── registry_ops/            # results / publish / login / org / list
│   │   ├── plugin_ops/
│   │   ├── agent_ops/               # --agent (+ optional --model) projects into profiles
│   │   └── local_jobs/              # local Job list / get / delete
│   ├── attempt/                     # deep module: one Attempt’s visible pipeline
│   │   ├── __init__.py              # run_attempt five-phase lines
│   │   ├── ctx.py
│   │   ├── emit.py                  # chain-slot next()
│   │   └── phases/
│   │       ├── environment.py
│   │       ├── run.py
│   │       ├── evaluate.py
│   │       ├── record.py
│   │       └── cleanup.py
│   ├── config/                      # dataset root + task.yaml + profiles
│   ├── environments/
│   │   ├── protocol.py              # EnvironmentProvider · StdioTransport · caps
│   │   └── streams.py
│   ├── plugins/
│   │   ├── slots.py                 # exclusive / chain ids
│   │   ├── registry.py / resolve.py / bootstrap.py
│   │   ├── defaults/                # environment_setup recognizes setup.sh
│   │   └── contrib/
│   │       ├── acp/                 # exclusive executor + attach_stdio client
│   │       ├── docker/              # exclusive environment
│   │       ├── local/
│   │       ├── e2b/
│   │       ├── daytona/
│   │       ├── ssh/                 # A whole host / B remote container
│   │       ├── openai_http/
│   │       └── anthropic_http/
│   ├── runtime/
│   │   ├── identity.py
│   │   ├── parent_agent.py          # executor service + host.attach_stdio only
│   │   ├── task_launch.py           # Control Plane subprocess runs run.py
│   │   └── task_worker.py
│   ├── evaluation/                  # barrier + in-environment runner + bind PASS
│   ├── evidence/                    # sole owner of layout strings
│   ├── capabilities/
│   ├── registry/                    # Hub client
│   ├── viewer/                      # local Jobs HTTP
│   ├── control/
│   └── agents/                      # ageval.agent/1 cache + builtin catalog
│       ├── builtin/                 # catalog.json + shipped harness trees
│       └── reserved.py              # short ids: overlay, not Hub upload
├── src/ageval_sdk/                  # RunContext / RunTerminal / AgentSession (same distribution as ageval)
├── apps/
│   ├── viewer/                      # `ageval view` SPA
│   └── hub/                         # Registry Dataset / Plugin / Agent / Leaderboard
├── services/registry/               # standalone HTTP: Route.access + *Service
│   ├── app.py / http_api.py / asgi.py / backend.py
│   ├── auth_service.py / package_service.py / result_service.py / org_service.py
│   ├── request_service.py           # listing + performance requests; Inbox
│   ├── queries.py / dataset.py / sql_adapter.py
│   ├── store_schema.py              # open_stores: schema once → RegistryStores
│   ├── store_package.py / store_result.py / store_org.py / store_inbox.py
│   ├── blobs.py / tokens.py / rows.py / protocols.py   # narrow store protocols
│   ├── store.py                     # row/DTO vocabulary + re-exports
│   └── routes.py                    # ROUTES must declare access
├── examples/
│   ├── datasets/
│   │   ├── minimal-demo/            # terminal-jsonl-agg / tau2-dialog-min / multiagent-env-min
│   │   └── tau3-airline-5/            # airline-00 … airline-04 lock
│   └── agents/                      # ageval.agent/1 catalog packages
├── plugins/                         # external ageval.plugin/1
│   ├── nooa/ / dsh/ / miniswe/ / acp-oneshot/
│   └── home-files/ / agent-skills/
├── docker/attempt/                  # official base: ACP entries written at image build
├── tests/
├── docs/
└── website/
```

Hub Agent Performance is a **derived view** of plaza / consented `job_overlay.agent_ref` rows, not a Core object. Builtin cards default to official public suites auto-collect; Maintainers (`AGEVAL_REGISTRY_MAINTAINERS`) own that setting and builtin attach approval. There is no `/runtimes` product surface. Public Leaderboard listing is a Registry flag (`board_listed`), not visibility. Delayed `agent_ref` attach and request decide share one ResultService write path; CLI `build_results_commands` is the Hub/CLI use-case root.

Production Attempt: `application/run.py` mints identity once, then `attempt.run_attempt`. Cleanup is in `try/finally`. Parent Agent Service and hard ceilings share the same quota object.

### Target Source Layout (not fully realized)

This is the accepted direction, **not** splitting Current back into `adapters/` + `run_l0.py`.

```text
src/ageval/
  cli/ application/ attempt/phases/ config/
  environments/protocol.py          # still no vendor SDK
  plugins/contrib/{acp,docker,local,e2b,daytona,ssh,openai_http,anthropic_http}
  plugins/defaults/                 # or move to contrib/defaults — pick one, not both
  runtime/{identity,parent_agent,task_launch,task_worker}
  evaluation/{bind,package_evaluator} + runtime/eval_worker.py
  evidence/{locators,store,trajectory}
```

**Deliberately not built (deleted in Current; Target must not bring them back):**

- `environment/manager.py`
- catch-all `adapters/`, `agent_container.wrap_docker_exec`
- forked lifecycle modules (Attempt goes only through `attempt/phases/`)
- product `executor: mock` / FakeHost

### Generated artifacts (not source ownership)

| Path / pattern | Notes |
| --- | --- |
| `.ageval/` | runs, suite-runs, local plugin cache, credentials |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | toolchain |
| `dist/`, `*.egg-info/` | build artifacts |

## Module Ownership (Current)

| Path | Sole responsibility | Does not own |
| --- | --- | --- |
| `cli/` | argv, help, exit code | Reading task business logic, starting Docker, assembling evidence paths |
| `application/` | lock/run/campaign/suite/registry/plugin/agent/jobs; **wiring** | Hiding business rules in global singletons outside bootstrap |
| `application/composition.py` | Sole production `build_*` | Business algorithms |
| `config/` | dataset resolve; read `task.yaml` / profiles; digest | Executing `run.py`, scoring |
| `attempt/` | Phase order, `emit`, AttemptCtx | Vendor SDKs, `container_id` |
| `environments/` | Protocol + caps + stream shapes | `import e2b` / `docker` / `paramiko` |
| `plugins/contrib/docker/` | `docker exec`, compose, uid/gid, images | ACP protocol |
| `plugins/contrib/e2b/` | E2B SDK, template alias (cached on that account; Core does not implement) | A Core cache layer |
| `plugins/contrib/ssh/` | ssh A/B, `ssh -T` / `docker exec` | A fake in-process agent |
| `plugins/contrib/acp/` | Parent ACP client, entry registry, consumer of `attach_stdio` | Layer-C writer; vendor stdout scrape |
| `plugins/defaults/` | `environment_setup` recognizes `setup.sh`; default winners for `evaluation_runtime` / `trajectory_seal` | Fake executor; PASS |
| `runtime/` | identity, parent Agent Service, task-worker subprocess, cancel/timeout | Box implementations, scoring |
| `evaluation/` | Barrier order, in-environment runner, flat Result | Task scoring algorithms |
| `evidence/` | store / redaction / layer-C `trajectory.jsonl` | Vendor protocol parsing; PASS |
| `registry/` + `services/registry/` | PackageRef, publish, verified cache; standalone HTTP | PASS; handing store credentials to the CLI |
| `ageval_sdk` | Task types and thin helpers | Control Plane internal types, verdict |
| `examples/` | Trusted regression datasets | Claiming a full upstream suite |
| `tests/` | Contracts and regression | Becoming the production composition root |
| `docs/` | Design and product spec | Version-checkbox status |
| `website/` | Reader-facing usage | Design authority |

## Dependency Direction

Dependency arrows = **allowed Python import direction**.

```text
cli ──────────────► application.composition
                         │
                         ├─► config / attempt / runtime / capabilities / evaluation
                         │
                         └─► plugins.bootstrap ──► contrib/* ──► environments.protocol
                                                    (contrib is not imported back by protocol)

ageval_sdk ──► public DTOs / protocol shapes only
               (must not import application, contrib internals, or Control Plane private modules)
```

### Forbidden

- `environments/protocol.py` depending on Typer, Docker SDK, e2b SDK, or SQLAlchemy.
- CLI calling Codex directly, writing the evidence tree, or parsing task business logic; CLI bypassing composition.
- Control Plane importing/executing task `run.py` / `evaluator.py` **as Python modules** (must be a process or adapter boundary).
- SDK obtaining host credential file contents, Docker-socket control, or final-result publish rights.
- Implicitly registering a global Adapter singleton **outside** the composition root.
- Adapters choosing behavior by Benchmark name, task id, or upstream brand.
- `container_id` or `if kind == e2b` appearing in ACP / `attempt` / `run.py`.
- A second `resolve_executor` / CLI bypass / hand-constructing Docker in application.
- Production code importing a test helper as the only wiring path.

Third-party workflow SDKs: allowed only as a task or **explicit** external plugin dependency; they must not become Core authority.

## Composition Root

| Item | Rule |
| --- | --- |
| Sole production wiring point | `build_*` in `src/ageval/application/composition.py` |
| New public use case | Must have a matching `build_*` |
| CLI | Imports only `ageval.application.composition` (and `ageval.cli` itself) |
| Tests | May use test-only wiring; public smoke must go through production CLI |
| Plugin discovery | Extension registry + `ageval plugin install` local cache; missing plugins are rejected and the run does not start; no `ageval.agent_executors` dual path |

## Extension emit map (Current)

The host **awaits** registered chain slots / exclusive winners. Plugins rewrite or short-circuit via `(ctx, value, nxt)`; they do **not** drop declaration rows for Core to interpret later.

Slot-name authority: `src/ageval/plugins/slots.py`. Only **exclusive** and **chain**. Current exclusive slots: `environment`, `executor`, `evaluation_runtime`, `trajectory_seal`. `environment` / `evaluation_runtime` / `trajectory_seal` are Attempt-wide; `executor` is one winner **per profile graph**. The last two default to the engine (`plugin_id: default`). PASS still enters Result only through `bind_evaluation`; `evaluation_runtime` returns raw and must not write a verdict itself. `pass` / `identity` / `cleanup` / `evidence` are not services.

```text
environment phase
  before_environment
  host.start
  upload data/ → /attempt/workspace
  after_environment_ready      # ACP probe; skip install when bake matches
  environment_setup            # setup.sh (defaults)
  after_environment

run phase
  before_run
  subprocess python -m ageval.runtime.task_worker → run.py
    Agent.session → unix socket → ParentAgentService
      before/after_agent_open
      before_agent_invoke → this profile's executor.invoke → after_agent_invoke
      normalize_agent_result
      before/after_agent_close
  seal_run (solver writers stopped; Agent Service stays up); mark_writers_stopped
  after_run

evaluate phase
  before_evaluate
  [evaluate_host.isolated, no named map] start second EnvironmentProvider (docker; distinct work root)
  [no named map] upload artifacts / tree snapshot / evaluation/ onto that scoring host
  [isolated, no named map] after_environment_ready for evaluate-phase ACP profiles
  evaluation_runtime.evaluate  # exclusive-slot winner; default parent evaluator.py worker
                               # named map: lazy start on scoring.exec / session(environment=)
                               #            ACP must name the host; omit / run-phase target fails
                               # optional Agent.session(<judge>).invoke via parent socket
                               # isolated: ACP attach_stdio hits the (named) scoring host
  bind_evaluation              # PASS enters Result only here
  after_evaluate               # must not change status

record phase
  trajectory_collect → enrich  # later steps still run if this hook fails
  trajectory_seal              # exclusive-slot winner writes run-phase trajectory.jsonl
  evaluation/observation.jsonl # evaluate-phase trajectory.jsonl when SDK invoked (omit user)
  summary_enrich               # later steps still run if this hook fails; Attempt summary.extra (omit when empty)

cleanup (finally)
  cleanup_report
  evaluate_host.stop           # each started isolated scoring host
  host.stop
```

`FAIL_OPEN_SLOTS`: `before_run` / `after_run` / `trajectory_collect` / `trajectory_enrich` / `summary_enrich` / `cleanup_report`. Any other slot failure fails that phase.

## Lifecycle (Current)

### Outer states (Attempt)

```text
created
  → locking          # load_and_lock
  → preflight        # host.preflight; missing keys fail here
  → environment      # start + seed + setup
  → run              # run.py + ACP
  → evaluate         # stop writers + gold + bind
  → record
  → cleanup          # finally; entered on every failure path
  → terminal         # PASS | FAIL | ERROR
```

### Order invariants

1. Must not `start` a box or invoke until `load_and_lock` succeeds.
2. Evaluator must not face the same scoring inputs concurrently with a writable Agent/`run.py` writer. Gold is uploaded only at the start of evaluate.
3. `cleanup` must be reachable from timeout/cancel/exception; cleanup failure → warning, does not overwrite a bound score.
4. Retry / re-run → a **new Attempt**; do not silently rewrite the old Attempt identity. One Attempt calls `IdentityFactory.new_run` once.
5. Campaign schedules Trials/grid points only; it does not merge with the workflow inside `run.py`.

Phase detail: [docs/design/05-runtime/lifecycle.md](docs/design/05-runtime/lifecycle.md).

## Data Flow (Current)

| Data | Producer | Consumer | Boundary rule |
| --- | --- | --- | --- |
| `ageval.yaml` + `task.yaml` + `profiles.yaml` | Author / CLI | Config | Sole spec reader; unknown format is one error |
| `LockedTaskConfig` + `extension_bindings` | Config | Attempt, box, executor, Evaluation | Replayable; no secret plaintext |
| `ctx.params` | Config projection | `run.py` | Read-only; no gold/credential |
| Agent prompt / tools | `run.py` | ACP / other executor | Must not include secrets by default |
| Credential material | Host env | Approved executor subprocess only | Locator; never in lock/evidence |
| Workspace bytes | Box upload/bind | Agent and `run.py` visibility | Contract path `/attempt/workspace` |
| Published artifacts | `ctx.publish_json` | evaluate upload | Logical name + allowlist |
| Evaluator raw | Task `evaluator.py` | `bind_evaluation` | Independent materialization; same box |
| Flat Result | Evaluation | CLI / evidence / aggregation | `status`/`score`/`kind`/`logs` |
| Evidence tree | `evidence/` | Humans and later tools | No secrets; locatable |

## Platform Boundary (Current)

| Platform capability | Owner | Notes |
| --- | --- | --- |
| `environment: local` | `plugins/contrib/local` | Real directory |
| `environment: docker` | `plugins/contrib/docker` | Real container; compose / uid_gid / path_views |
| `environment: e2b` | `plugins/contrib/e2b` | SDK only in this package; missing `E2B_API_KEY` fails preflight |
| `environment: ssh` A/B | `plugins/contrib/ssh` | A has no image; B has a remote tag |
| ACP coding-agent | `plugins/contrib/acp` | Sole coding-agent inlet; `attach_stdio` |
| Other Agent backends | `openai-http` / `anthropic-http` / external `nooa` `dsh` | Not vendor stdout scrape |
| Official base image | `docker/attempt/` | Bake every shipped ACP entry at build; no `npm i` at invoke |
| ACP task image layer | `plugins/contrib/acp` | `config.image_layers` bakes the bound `options.entry` onto the task recipe |
| Registry HTTP | `services/registry/` | Handlers go through `*Service`; persistence is four aggregate stores (`store_*.py`) behind narrow protocols, one schema init in `store_schema.open_stores`, SQL only in `queries.py`, dialect only in `sql_adapter.py` |

## Failure and Privacy Boundary

| Failure class | Appearance | Owner |
| --- | --- | --- |
| Config / lock failure | Non-zero; no fake PASS | Config / CLI |
| Unknown format | `invalid_format` at `/format` | Config |
| Missing cap / missing inject | lock fails | Config / plugins |
| Missing keys (e2b/ssh/ACP) | One preflight or invoke failure | Box / executor |
| Unauthorized effect | Rejected before execute | Capability / box |
| Agent infrastructure error | ERROR; may have no score | runtime / executor |
| Low eval score | FAIL + score; Attempt still complete | Evaluation |
| Agent / evaluate time budget | FAIL, score 0, `metrics.reason=timeout` | Attempt |
| Evaluator crash (not timeout) | `error.phase = evaluate` ERROR | Evaluation |
| Cleanup failure | warning | Box / Attempt |
| User cancel | Enters cleanup | Attempt / runtime |

Privacy: tokens, `CODEX_HOME` contents, DB passwords, and SSH private keys must not appear in lock, default logs, or evidence body.

## Testing and Evidence

| Grade | Meaning | When you may claim it |
| --- | --- | --- |
| `design-only` | Docs only | Paths not covered by public smoke (including real e2b/ssh runs when keys are absent) |
| `runnable-mvp` | Real public entrypoint + real Agent | Matching public demo exists (current: core local/docker ACP, named `minimal-demo` tasks) |
| `isolated` | Isolated Attempt + isolation red lines | Matching acceptance evidence; do not infer from one docker PASS |
| `real-benchmark-verified` | Fixed upstream + bounded public journey | Matching acceptance; do not expand to the full suite |

| Test layer | Use | Cannot prove alone |
| --- | --- | --- |
| unit | Pure rules, schema, phases | The product runs |
| integration | Wiring | Real ACP / E2B / SSH |
| e2e / public smoke | Production CLI | — |

Fixtures and mocks must not raise the evidence grade. `AGEVAL_SKIP_REAL_ACP=1` only means CI did not run that path.

## Change Ownership

| Change type | Update first | Then sync |
| --- | --- | --- |
| Top-level dirs, module ownership, import direction, composition root | **This document** | Root `AGENTS.md`, code |
| Product/mechanism design, red lines, box Protocol | `docs/design/*` (PRD if needed) | Related sections here, Issues, website |
| Implementation-time user-named binding decisions | Write into related `docs/design/*` or `AGENTS.md` red lines | Code, Issues |
| Incremental delivery and acceptance tracking | GitHub Issues | PR, smoke, README status |
| Implementation delta and evidence | Code / tests / public smoke | Issues |
| CLI user entry or publicly supported scope | `README.md` + `website/` | docs summary |
| Reader-facing usage (CLI / Viewer / Hub) | `website/` | If it conflicts with docs, docs win |

## Split with the design docs

| Question | Read |
| --- | --- |
| Product stories / naming / non-goals? | [docs/design/00](docs/design/00-overview-and-product.md) |
| Why this Core / five-phase cut? | [docs/design/01](docs/design/01-ageval-core.md) |
| `ageval.yaml` fields and lock? | [docs/design/02](docs/design/02-task-package-and-config.md) |
| `run.py` / SDK API? | [docs/design/03](docs/design/03-task-run-and-sdk.md) |
| Box kind / ACP / evaluate / evidence? | [docs/design/05-runtime/](docs/design/05-runtime/) |
| Plugin exclusive/chain? | [docs/design/11](docs/design/11-extension-plugins.md) |
| Evaluation and failure semantics? | [docs/design/07](docs/design/07-budget-evaluation-failure.md) |
| Full owner matrix? | [docs/design/09](docs/design/09-owner-matrix-and-structure.md) |
| Where source lives, who depends on whom, lifecycle diagrams? | **This document** |
