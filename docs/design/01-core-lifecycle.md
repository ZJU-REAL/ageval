# 01 — Core Lifecycle, Quotas, and Failure Semantics

This specification defines the authoritative execution pipeline of **ageval Core**: configuration locking (`lock`), Attempt identity and phase state transitions, resource limits (`limits`), upstream stall handling, suite resumption and regrade semantics, and structured failure reporting.

Module layout and import boundaries are specified in [ARCHITECTURE.md](../../ARCHITECTURE.md). Dataset and configuration schemas are specified in [02-schemas-and-config.md](02-schemas-and-config.md).

---

## 1. Scope and Core Invariants

1. **Lock before execution**: No environment may start and no model or tool invocation may occur before `load_and_lock` succeeds and produces an immutable `LockedTaskConfig` with its canonical `digest`.
2. **Fixed phase pipeline**: Every Attempt executes the fixed top-level sequence `environment → run → evaluate`, followed unconditionally by `record` and `cleanup` inside a `finally` block (`src/ageval/attempt/__init__.py`). Plugins may hook into phase slots but MUST NOT reorder phases or bypass `cleanup`.
3. **Evaluation barrier and gold isolation**: Reference materials under `tasks/<id>/evaluation/` (`gold`) MUST NOT be mounted or uploaded during `environment` or `run`. Before `evaluate` begins, `seal_run` cancels queued solver calls, drains in-flight solver calls, and marks solver writers stopped (`mark_writers_stopped`).
4. **Verdict exclusivity**: `PASS` and `FAIL` verdicts come solely from `evaluator.py` via `AttemptCtx.bind_evaluation` during the `evaluate` phase. `RunTerminal.completed`, ACP `end_turn`, or full quota consumption never imply `PASS`.
5. **Pre-effect quota enforcement**: Core enforces `limits` (`environment_seconds`, `wall_time_seconds`, `evaluate_seconds`, `agent_invocations`, `agent_concurrency`) before dispatching external effects. Reaching a `run`-phase quota (`wall_time_seconds` or `agent_invocations`) seals solver sessions and proceeds to `evaluate` so harvested artifacts are still graded (`PASS` or `FAIL`).
6. **Immutable settled evidence**: Once `.ageval/runs/<attempt_id>/result.json` is written, the Attempt directory is immutable. Retries (`--retry-errors`), slot replacements (`--replace-slot`), and regrades (`ageval results regrade`) always mint a new Attempt.
7. **Zero plaintext secrets in evidence**: API keys and credentials are referenced exclusively by environment variable names (locators) and redacted via `redact_and_assert` before writing `lock.json`, `result.json`, `trajectory.jsonl`, or `summary.json`.
8. **Single composition root**: All production platform objects are wired exclusively inside `build_*` functions in `src/ageval/application/composition.py`; `cli/` imports only `composition`.

---

## 2. Identity Hierarchy and State Machine

### 2.1 Identity hierarchy

A single task execution mints three identifiers via `IdentityFactory` (`src/ageval/runtime/identity.py`):

| Entity | Scope | Cardinality and Persistence |
| --- | --- | --- |
| **Run** (`run_id`) | Single CLI execution of a task | Minted once per Attempt via `IdentityFactory.new_run`. |
| **Trial** (`trial_id`) | `(task_id, locked_config_digest)` | Binds the run to the canonical lock digest via `IdentityFactory.new_trial`. |
| **Attempt** (`attempt_id`) | Single execution directory | Stored at `<dataset>/.ageval/runs/<attempt_id>/`. |
| **Suite Run** (`suite_run_id`) | Dataset-wide multi-task run | Stored at `<dataset>/.ageval/suite-runs/<suite_run_id>/`; indexes member task Attempts in `task_refs[]`. |

### 2.2 Outer Attempt state machine

```text
created
  │
  ▼
locking        load_and_lock: validate schemas, capabilities, ExtensionGraph, ModelSpec → digest
  │
  ▼
preflight      host.preflight: verify daemon / sandbox credentials before provisioning
  │
  ▼
environment    before_environment → host.start → upload data/ → after_environment_ready → environment_setup → after_environment
  │
  ▼
run            before_run → subprocess run.py (ParentAgentService socket) → mark_writers_stopped → harvest task-artifacts/ → seal_run → after_run
  │
  ▼
evaluate       before_evaluate → evaluation.collect → upload evaluation/ & artifacts → evaluation_runtime.evaluate (evaluator.py) → bind_evaluation → after_evaluate
  │
  ▼ (finally: runs on normal completion, quota limit, timeout, cancellation, or unhandled exception)
record         trajectory_collect → trajectory_enrich → trajectory_seal (trajectory.jsonl) → summary_enrich (summary.json)
  │
  ▼ (finally)
cleanup        stop isolated scoring host(s) → host.stop → cleanup_report
  │
  ▼
terminal       result.json written with status: PASS | FAIL | ERROR
```

If an unhandled exception or timeout occurs in `environment`, `run`, or `evaluate`, Core records the first `phase_failed` fact and skips remaining business phases. Once the environment has started, `finally` still executes `record` (archiving all trajectory events collected up to the failure point) and `cleanup` (stopping all started environments). If `record` itself raises after a prior phase error, Core records a `record_warning` fact without overwriting the original phase error.

---

## 3. Configuration Locking and Phase Pipeline Contracts

### 3.1 Configuration locking (`ageval lock`)

`src/ageval/config/load_and_lock.py` is the sole reader of `ageval.yaml` (`ageval.dataset/1`), `tasks/<id>/task.yaml` (`ageval.task/1`), and `profiles.yaml` (`ageval.profiles/1`).

```text
CLI (--task / --profiles / --agent / --model / --set / --layout)
  → resolve dataset & task manifest (native ageval.dataset/1 or explicit --layout harbor)
  → merge task.yaml + profiles.yaml (or projected --agent package)
  → validate format ("ageval.*/1") and reject unknown keys
  → verify task requires.environment ⊆ environment.capabilities
  → resolve ExtensionGraph (exclusive slots + priority-ordered chain slots)
  → verify plugin inject dependencies and BaseExecutor.supports_model(ModelSpec)
  → canonicalize and hash → LockedTaskConfig (digest + extension_bindings)
```

- **Format validation**: Any unknown `format` string fails immediately with `invalid_format` at `/format`.
- **CLI profile flags**: `--profiles` and `--agent` are mutually exclusive. `--model` requires `--agent` and overrides `model.id` on bound role profiles. `--set` may override only allowlisted paths ([02-schemas-and-config.md](02-schemas-and-config.md)); `limits.*` cannot be modified via `--set`.

### 3.2 Top-level phase pipeline (`src/ageval/attempt/__init__.py`)

```python
async def run_attempt(ctx: AttemptCtx) -> None:
    try:
        await environment.run(ctx)  # Provision host, upload data/, probe runtime, run setup.sh
        await run.run(ctx)          # Execute run.py, stop writers, harvest artifacts, then seal_run
        await evaluate.run(ctx)     # Upload evaluation/ (gold), run evaluator.py, bind verdict
    finally:
        await record.run(ctx)       # Seal trajectory.jsonl, observation.jsonl, and summary.json
        await cleanup.run(ctx)      # Stop scoring host(s) and run host; emit cleanup_report
```

### 3.3 Phase responsibilities and extension slots (`src/ageval/plugins/slots.py`)

| Phase | Default Implementation (`attempt/phases/`) | Exclusive Slots Used | Chain Slots Emitted (in order) |
| --- | --- | --- | --- |
| `environment` | Starts `ctx.host`, uploads `data/` to `/attempt/workspace`, prepares `$HOME` overlays and ACP runtime, runs `environment/setup.sh`. | `environment` (Attempt-wide) | `before_environment` → `after_environment_ready` → `environment_setup` → `after_environment` |
| `run` | Runs `run.py` in a child process connected to `ParentAgentService` over a Unix socket. After solver writers stop, declared `artifacts.publishable` are copied into `task-artifacts/`, and `seal_run` is recorded only after that copy succeeds. | `executor` (per role profile) | `before_run` → `before/after_agent_open` → `before/after_agent_invoke` → `normalize_agent_result` → `before/after_agent_close` → `after_run` |
| `evaluate` | Runs optional `evaluation.collect`, uploads `evaluation/` (`gold`) and harvested artifacts to the scoring host (reused run host, single `evaluate_host.isolated` container, or lazy named `evaluation.environments`), runs `evaluator.py`, and calls `ctx.bind_evaluation`. | `evaluation_runtime` (default: `default`), `executor` (for optional `judge` roles) | `before_evaluate` → `after_evaluate` |
| `record` | Collects and seals run-phase events into `trajectory.jsonl` (and evaluate-phase judge events into `evaluation/observation.jsonl`), then enriches `summary.extra`. | `trajectory_seal` (default: `default`) | `trajectory_collect` → `trajectory_enrich` → `summary_enrich` |
| `cleanup` | Stops all started isolated scoring hosts and `ctx.host` (`delete = not ctx.keep_workspace`). | `environment` | `cleanup_report` |

- **Fail-open vs. fail-fast slots**: `FAIL_OPEN_SLOTS` consists of `before_run`, `after_run`, `trajectory_collect`, `trajectory_enrich`, `summary_enrich`, and `cleanup_report` (exceptions in these slots record a warning fact and allow the phase to continue). An exception in any other slot immediately fails the enclosing phase.

---

## 4. Resource Quotas (`limits`), Concurrency, and Upstream Stall

### 4.1 Phase clocks and invocation quotas

`limits` are declared in `task.yaml` and enforced by `AttemptCtx` and `ParentAgentService` prior to external effects. Post-hoc token and cost metrics are observational.

| Limit Key | Default | Enforced Scope | Behavior When Reached |
| --- | --- | --- | --- |
| `limits.environment_seconds` | `600` | `environment` phase (`host.start`, `data/` upload, `after_environment_ready`, `environment_setup`) | Raises `TimeoutError("environment_timeout")`; Attempt terminates as `ERROR` (`phase: "environment"`), and `run` does not start. |
| `limits.wall_time_seconds` | `300` | `run` phase (from phase entry until `run.py` exits and solver calls drain) | Records `limit_reached: "wall_time_seconds"`, seals solver sessions, harvests existing workspace artifacts, and proceeds to `evaluate`. On recovery, `arm_phase_budget` subtracts the active `elapsed_ms` already recorded on completed steps in that phase. If the remainder is already `<= 0`, `run` records the limit and does not start another solver effect. |
| `limits.evaluate_seconds` | `600` | `evaluate` phase (`evaluation.collect`, scoring host startup/upload, `evaluator.py`, `scoring.exec`, and `judge` calls) | Raises `TimeoutError("evaluate_timeout")`; Attempt terminates as `ERROR` (`phase: "evaluate"`). |
| `limits.agent_invocations` | `1` | `run`-phase `executor.invoke` calls across all solver sessions (`judge` calls in `evaluate` are exempt) | Atomic reservation via `AgentInvocationQuota.try_consume()` right before `executor.invoke`. Refuses new solver calls with `quota_exceeded`, records `limit_reached: "agent_invocations"`, and proceeds to `evaluate`. |
| `limits.agent_concurrency` | `1` | Maximum concurrent `running` solver invocations in `ParentAgentService` | Calls within a single `session_id` serialize in arrival order; calls across distinct sessions overlap up to `agent_concurrency` on executors with `concurrent_sessions = True` (`acp`, `openai-http`). |

When `wall_time_seconds` or `agent_invocations` is reached during `run`, `evaluator.py` still grades the harvested artifacts (`PASS` or `FAIL`). `result.json` records the triggered quota name in `limit` (first hit wins) and leaves `error` as `null`.

### 4.2 Upstream stall handling (`upstream_stall`)

When `executor.invoke` encounters a retryable transport failure (`TransportStall`), `ParentAgentService` enters `upstream_stall` rather than failing the Attempt on transient network or gateway outages:

1. **Budget and interval**: Controlled by `options.upstream_stall_seconds` on the role profile (default `3600` seconds from `src/ageval/runtime/clocks.py`; `0` disables retries). Retries occur at a fixed `60`-second interval (`stall_interval`).
2. **Phase clock freeze**: While at least one invocation is in `upstream_stall`, `AttemptCtx.freeze_phase_clock()` freezes the active phase countdown (`wall_time_seconds` or `evaluate_seconds`) using a reference counter (`_clock_holds`). The clock resumes via `thaw_phase_clock()` only when the last stalled invocation exits stall.
3. **Quota preservation**: Retries of the same admitted `invoke` inside `upstream_stall` do not consume additional `agent_invocations` quota.
4. **Retryability rules by executor**:
   - **Pre-invocation parent refusals** (expired phase clock, exhausted `agent_invocations`, `RedactionError`, or `AGEVAL_OFFLINE_AGENT=1`) fail immediately without entering `upstream_stall`.
   - **`openai-http` and `anthropic-http`**: Socket timeouts, connection errors, HTTP `408`, `429`, and `5xx` raise `TransportStall` (`repeatable=True`). Other HTTP `4xx` responses raise non-retryable `ModelConfigError`. Malformed JSON raises `ProtocolError`.
   - **`acp`**: Idle timeout (`acp_idle_timeout`), prompt timeout (`acp_timeout`), unexpected EOF (`acp_unexpected_eof`), and protocol errors raise `TransportStall`, and are retried on the session only if no non-readonly tool call has modified the workspace during that turn (`_workspace_unchanged(events) == True`).
   - **`miniswe` and `terminus-2`**: Stall retries wrap each individual model HTTP request inside the parent loop while preserving prior turns in the episode.
5. **Observability**: `summary.json` records an `upstream_stall` fact containing the failure reason, `started_at`, retry count, and terminal outcome (`resumed`, `budget_exhausted`, or `not_repeatable`).

---

## 5. Suite Resumption, Slot Replacement, and Regrade

All settled Attempt directories (`.ageval/runs/<attempt_id>/` containing `result.json`) are immutable (for recovery of unsealed Attempts lacking `result.json`, see [RFC 0001](../RFCs/0001-attempt-activity-recovery.md)):

| Operation | CLI Invocation | Identity Behavior | Execution Semantics |
| --- | --- | --- | --- |
| **Resume suite** | `ageval run <dataset> --resume-suite <suite_run_id>` | Keeps `suite_run_id`. Reuses an unsealed Attempt whose `activity.jsonl` header matches `(suite_run_id, task_id, attempt_index)` and `locked_config_digest`. | Skips slots that already have a settled `result.json` (`PASS`, `FAIL`, or `ERROR`). Recovers a matching unsealed Attempt in place. A slot with no activity header, or a digest mismatch, mints a new Attempt. `suite_cancelled` placeholders still run. |
| **Resume Attempt** | `ageval run <dataset> --task <id> --resume <attempt_id>` | Keeps that `attempt_id` | Recovers one unsealed directory in place. The reopened activity log uses the evidence store's redaction sentinels. Exit `2` with no new `result.json` when `result.json` already exists, the lock digest does not match, or the environment stays `busy`. `run` is skipped only when `seal_run` is complete and every declared publishable artifact is present under `task-artifacts/`. A task with no publishable artifacts needs only `seal_run`. |
| **Retry errors** | `ageval run <dataset> --resume-suite <id> --retry-errors` | Keeps `suite_run_id`; mints **new** Attempt per retried slot | Re-runs slots whose current status is `ERROR` (`PASS` and `FAIL` remain skipped). Moves the old Attempt reference into `previous[]` on the slot. |
| **Replace slot** | `ageval run <dataset> --resume-suite <id> --task <t> --replace-slot` | Keeps `suite_run_id`; mints **new** Attempt for target slot | Re-runs the targeted `(task_id, attempt_index)` slot regardless of prior status (`PASS`, `FAIL`, or `ERROR`) and moves the prior Attempt into `previous[]`. |
| **Regrade** | `ageval results regrade <dataset> --run <attempt_id>` | Mints **new** Attempt | Skips `run` (`run.py`, solver sessions, and `evaluation.collect` commands do not run). Copies archived `task-artifacts/` and `verifier-collect/` from the source Attempt into a fresh scoring environment and runs `evaluate → record → cleanup`. |

During `regrade`, if the source Attempt is missing declared publishable artifacts under `task-artifacts/`, the new Attempt terminates immediately as `ERROR` (`phase: "evaluate"`, `title: "regrade_harvest_missing"`). Trajectory text is never substituted for missing workspace artifacts.

---

## 6. Result Schema, Exit Codes, and Error Reference

### 6.1 `Result` (`result.json`) status and `error` envelope

`result.json` records `status` (`"PASS" | "FAIL" | "ERROR"`), `score` (`float`), `limit` (`str | null`), `error` (`{phase, title, message} | null`), and `logs` (portable locator to the Attempt directory).

- When `status` is `"PASS"` or `"FAIL"`, `error` MUST be `null`.
- When `status` is `"ERROR"`, `error` is a required object `{phase, title, message}` where `title` is resolved in priority order:
  1. `ScriptError(title, message)` raised explicitly by `run.py` or `evaluator.py`;
  2. The unhandled exception class name raised by a task script (e.g., `"ValueError"`);
  3. The engine-defined failure token from the table below.

### 6.2 CLI exit codes and canonical failure table

| Exit Code | Meaning |
| --- | --- |
| `0` | All executed tasks finished with `PASS` (or `ageval lock` / `--probe` succeeded). |
| `1` | At least one task finished with `FAIL` and no task finished with `ERROR` (or `--probe` reported `ready: false`). |
| `2` | Configuration/lock error, preflight failure, or at least one Attempt finished with `ERROR`. |

| Failure Condition | `result.status` | `error.phase` | `error.title` / Error Code | Owner |
| --- | --- | --- | --- | --- |
| Unknown `format` in YAML manifest | *(no Attempt)* | `null` | `invalid_format` (exit `2`) | `config/` |
| Invalid `ModelSpec` or disallowed `model.extra` key | *(no Attempt)* | `null` | `model_config` (exit `2`) | `model/` · `config/` |
| Unsatisfied `requires.environment` or plugin `inject` | *(no Attempt)* | `null` | `capability_missing` / `plugin_resolve_failed` (exit `2`) | `config/` · `plugins/` |
| Missing cloud sandbox or SSH credentials | *(no Attempt)* | `null` | `environment_preflight_failed` (exit `2`) | `environments/` |
| `environment` phase exceeds `environment_seconds` | `ERROR` | `"environment"` | `environment_timeout` | `attempt/` |
| `environment/setup.sh` exits non-zero | `ERROR` | `"environment"` | `environment_setup_failed` | `plugins/defaults/` |
| ACP Node floor or binary check fails in `after_environment_ready` | `ERROR` | `"environment"` | `acp_runtime_node` / `acp_runtime_missing` / `acp_runtime_install_failed` | `plugins/contrib/acp/` |
| `run` phase reaches `wall_time_seconds` or `agent_invocations` | `PASS` or `FAIL` | `null` | `error` is `null`; `limit` set to quota name | `attempt/` · `runtime/` |
| `run.py` crashes or exits without returning `RunTerminal` | `ERROR` | `"run"` | `ScriptError.title`, exception class, or `task_worker_no_result` | `runtime/` |
| `evaluation.collect` command fails or path is missing | `ERROR` | `"evaluate"` | `environment_collect_failed` / `environment_collect_missing` | `attempt/phases/evaluate.py` |
| Source Attempt lacks `task-artifacts/` during `regrade` | `ERROR` | `"evaluate"` | `regrade_harvest_missing` | `application/regrade.py` |
| `evaluate` phase exceeds `evaluate_seconds` | `ERROR` | `"evaluate"` | `evaluate_timeout` | `attempt/` |
| `evaluator.py` returns status other than `PASS` or `FAIL` | `ERROR` | `"evaluate"` | `evaluator_invalid_status` | `evaluation/` |
| `evaluator.py` raises an unhandled exception | `ERROR` | `"evaluate"` | `ScriptError.title` or exception class name | `evaluation/` |
| `host.stop` fails during `cleanup` | *(unchanged)* | *(unchanged)* | Recorded as `cleanup_warning` fact in `summary.json`; does not overwrite bound `Result` | `attempt/phases/cleanup.py` |
| Middle line of `activity.jsonl` is not valid | `ERROR` | `"run"` | `activity_log_corrupt` | `evidence/` |
| Restarted `run.py` sends a different prompt for a logged `request_id` | `ERROR` | `"run"` | `session_alignment_mismatch` | `runtime/` |
| Cold rebuild or checkpoint restore fails | `ERROR` | `"environment"` | `recovery_rebuild_failed` | `attempt/` |
| `--resume` finds a settled Attempt, a digest mismatch, or a still-busy environment | *(unchanged or no Attempt)* | — | Exit `2`; `attempt_already_settled`, `locked_config_mismatch`, or `attempt_still_busy` does not write `result.json` | `application/` |
