# 07 — Evidence Archive, Suites, Campaigns, and Post-Run Analyzers

This specification defines the Attempt evidence directory layout (`.ageval/runs/<attempt_id>/`), `trajectory.jsonl` sealing and `usage` accounting, `slim_sealed_attempt` pruning, dataset-wide **Suite** and **Campaign** execution, and post-run read-only **analyzers** (`stats`, `hack`, `review`).

All `.ageval/runs` and `.ageval/suite-runs` path constants live exclusively in `src/ageval/evidence/`.

---

## 1. Attempt Evidence Directory Layout (`<dataset>/.ageval/runs/<attempt_id>/`)

| File / Directory | Schema / Format | Normative Description |
| --- | --- | --- |
| `lock.json` | Canonical lock JSON | Redacted `LockedTaskConfig` snapshot (retains credential env var locator names only). |
| `result.json` | `Result` schema | Final verdict (`status`, `score`, `kind`, `error`, `limit`, `logs`). Presence of `result.json` marks the Attempt as settled and immutable. |
| `trajectory.jsonl` | `ageval.trajectory.event/1` | Normalized `run`-phase interaction trajectory written by the `trajectory_seal` exclusive slot during `record`. |
| `activity.jsonl` | `ageval.activity/1` | Append-only pre-effect log (`attempt`, `session`, `invoke`, `model_turn`, `tool_call`, `compaction`, `phase`). A truncated final line is dropped. A broken non-final line seals `activity_log_corrupt`. Written during execution regardless of retention. Removed with `checkpoints/` after settlement unless `--keep-recovery-state`. |
| `checkpoints/` | `ageval.checkpoint/1` | Content-addressed snapshots of `box/{workspace,home,artifacts}`. Keyless auth files are not copied into `blobs/`. Part of the recovery bundle with `activity.jsonl`. |
| `evaluation/observation.jsonl` | `ageval.trajectory.event/1` | Optional `evaluate`-phase `judge` trajectory (`user` prompt rows omitted to protect `gold`). |
| `evaluation/checks.json` | `ageval.evaluation.checks/1` | Optional step-by-step grading breakdown returned by `evaluator.py`. |
| `summary.json` | `Summary` schema | Phase wall-clock durations (`phase_timing`), lifecycle `facts[]`, and optional plugin namespace `extra`. |
| `task-artifacts/` | File or tree snapshot | Workspace artifacts harvested at the end of `run` per `artifacts.publishable`. |
| `verifier-collect/` | Collected paths | Files copied from the Attempt container or Compose sidecars by `evaluation.collect` (manifest omits raw command strings). |

Document schemas for `summary.json`, `result.json`, and trajectory `terminal` events are defined in `src/ageval/evidence/documents.py` and exported to `apps/shared/lib/evidence.gen.ts` via `python3 scripts/gen_evidence_ts.py` (`--check` enforced in CI).

`Result.logs` (`evidence_path`) points to `<dataset>/.ageval/runs/<attempt_id>/`. `ageval evidence <logs> --out <dir>` re-verifies secret redaction before exporting a sealed archive.

---

## 2. Trajectory Pipeline, `terminal.usage`, `summary.extra`, and Post-Seal Pruning

### 2.1 Trajectory pipeline and Web UI surfaces
During an Attempt, interaction events pass through three stages:
1. **Raw vendor capture (`backend_raw`)**: Executor-native request/response payloads and stream chunks under `agent/invocations/` (or `evaluation/invocations/`).
2. **Normalized events (`ageval.trajectory.event/1`)**: Mapped by the executor or `trajectory_collect` chain slot into canonical event kinds (`thought`, `assistant`, `tool_call`, `observation`, `permission`, `terminal`), each stamped with top-level `profile_id` and `session_id`.
3. **Sealed trajectory (`trajectory.jsonl`)**: Merged and ordered by `trajectory_seal` during `record`. Completed steps for an invoke are kept when the executor's fresh event buffer starts after a resume or skips a step that `activity.jsonl` already recorded.

| Web UI Surface | Archive File | Source Phase | Viewer / Hub Location |
| --- | --- | --- | --- |
| Solver Trajectory | `trajectory.jsonl` | `run` phase role invocations | **Trajectory** tab |
| Judge Trajectory | `evaluation/observation.jsonl` | `evaluate` phase SDK invocations | **Verifier** tab (`Trajectory` toggle) |
| Deterministic Checks | `evaluation/checks.json` | `evaluator.py` `checks` list | **Verifier** tab (`Files` toggle) |

### 2.2 `terminal.usage`, `terminal.elapsed_ms`, and `extra` extension fields
```text
usage: { prompt_tokens, completion_tokens, cached_tokens, cost_usd }  # Canonical fields; omitted when unreported
extra: { ... }                                                       # Vendor-specific counters & plugin metadata
```
- **No fabricated zeros**: Canonical fields (`prompt_tokens`, `completion_tokens`, `cached_tokens`, `cost_usd`) are written only when reported by the backend. When unreported, lost on timeout, unparseable, or partial, `usage` records `unavailable` with reason `not_reported`, `lost_on_timeout`, `parse_failed`, or `partial` — never substituting `0`.
- **Sibling `extra` and `summary.extra`**: Vendor-specific counters and plugin observations live in JSON-safe `terminal.extra`. After `trajectory_seal` completes, Core emits `summary_enrich` starting from `{}`; each active plugin writes only under `summary.extra[<plugin_id>]`.
- **`terminal.elapsed_ms`**: Wall-clock invocation latency (`latency_ms`) is copied onto `terminal.elapsed_ms` during sealing.

### 2.3 Post-seal pruning (`slim_sealed_attempt`)
Once `trajectory_seal` succeeds in `record`, `slim_sealed_attempt` removes intermediate scratch directories (`agent/invocations/`, `evaluation/invocations/`, `backend_raw/`) by default, retaining only `lock.json`, `result.json`, `trajectory.jsonl`, `summary.json`, `task-artifacts/**`, `verifier-collect/**`, `evaluation/observation.jsonl`, and `evaluation/checks.json`. Operators may pass `--keep-vendor-raw` to retain `backend_raw/` and per-invocation scratch files, or `--keep-workspace` to retain the host workspace directory (`box/`).

Recovery-state retention is a separate policy. The recovery bundle is `activity.jsonl` plus `checkpoints/` (manifests and blobs). Core records it during execution whether or not it will be kept. An Attempt that has not sealed both `result.json` and `trajectory.jsonl` always keeps the bundle, so `--resume` does not require a retention flag. After both files exist, Core deletes the bundle unless `--keep-recovery-state` is set. The CLI flag wins over `AGEVAL_KEEP_RECOVERY_STATE`; an unset or false env value means delete. `--no-keep-recovery-state` forces deletion even when the env value is true. `--keep-workspace` does not retain the bundle and is not required to retain it.

`<attempt>/state` is environment probe state (nonce, cursor, inflight), not part of the recovery bundle. `local` and `docker` remove it when `stop(delete=True)` deletes `box/`. A sealed Attempt also drops it unless `--keep-workspace` is set.

### 2.4 Checkpoint listing

`ageval checkpoints <dataset> --run <attempt_id>` reads a retained recovery bundle and does not start an environment. Each row is one `checkpoints/seq_<N>.json` or an activity `checkpoint_seq` with no manifest. The row records `seq`, the lifecycle phase at that seq, whether the blobs are `available`, `incomplete`, or `missing`, and `forkable`. A non-forkable row includes `reason`:

| Reason | Meaning |
| --- | --- |
| `not_run_phase` | The cut is not inside `run` (environment, evaluate, record, or unknown). |
| `solver_sealed` | The cut is at or after the completed `seal_run` line. |
| `gold_exposed` | The cut is at or after `evaluate` started. Gold may already be on the box. |
| `multi_session` | The prefix contains more than one completed session. |
| `continuation_unsupported` | The single session executor is not `miniswe`, `terminus-2`, `openai-http`, or `anthropic-http`. |
| `not_a_completed_cut` | No completed activity line owns this seq. |
| `inconsistent` | The owner seq, manifest seq, or an open in-flight effect does not match the cut. |
| `checkpoint_incomplete` | The manifest file is missing. |
| `state_not_restorable` | The manifest exists but a blob or the solver session cannot be restored. |

A forkable cut is a completed `run`-phase snapshot before `seal_run` and before gold upload, with one restorable session of a supported executor and a complete manifest. Exit 2 when the Attempt directory is missing, the recovery bundle is gone (`recovery_state_missing`), or `activity.jsonl` is corrupt. A retained bundle with no forkable cut still exits 0.

### 2.5 Checkpoint fork

`ageval run <dataset> --task <id> --fork <source_attempt_id> --checkpoint <seq> --model <id>` mints a new Attempt and a fresh environment. It does not attach, roll back, or write the parent environment. `--fork` and `--resume` are mutually exclusive. `--agent` and `--profiles` are rejected because the harness stays fixed. Core re-locks from the source job overlay and applies only the model override. `--model` sets `/agent_profiles/<source role>/model/id` and does not require `--agent`.

Before the environment starts, Core rejects a cut that `ageval checkpoints` would mark non-forkable, an unsupported continuation executor, and any lock difference other than the solver model's `id`, `api`, `timeout`, `watchdog`, or `reasoning/effort`. The child copies the activity prefix through the selected seq, marks those payloads `inherited`, and copies the selected checkpoint blobs into its own directory. Later parent events are not copied. Inherited events are evidence, not new child calls: they do not restore invocation quota and they do not charge the parent's phase elapsed into the child clock. Replayed model steps report no inherited cost. Shared-prefix usage is summed separately on `fork.shared_prefix_usage`.

`result.json` and `summary.json` include `fork` (`ageval.fork/1`) when the Attempt is a fork: parent Attempt, checkpoint seq, source and child lock digests, model changes (`from` / `to`), the continuation model, and whether that model was the locked model. The field is omitted otherwise. Default pass@k and from-scratch rollups skip rows that carry `fork`.

### 2.6 Terminal action replay input

A settled Attempt writes `replay-input.json` (`ageval.replay.input/1`) next to `activity.jsonl`. The same retention policy owns both files: they are recorded during the run, kept while the Attempt is unsealed, and deleted together after `result.json` and `trajectory.jsonl` exist unless `--keep-recovery-state` / `AGEVAL_KEEP_RECOVERY_STATE` retains the bundle. There is no second retention flag.

The manifest records task, dataset, environment, image, and `eval_digest` identity, the tool semantics version, and the ordered action arguments. `replayable` is false when a command is missing, redacted, incomplete, concurrent with another open action, or outside the bound executor's terminal adapter. Redaction does not become an empty successful program. An executor with no terminal adapter writes `terminal_replay_unsupported` instead of a bash program.

`ageval replay <dataset> --run <attempt_id>` reads that manifest, or builds the same document from retained activity when the file is absent. It refuses before starting an environment when the bundle is missing, the activity is corrupt, an action is not executable, or task / dataset / environment / image / `eval_digest` / tool-semantics identity does not match the current lock. A missing source `eval_digest` is a warning, not a match claim.

The child `result.json` and `summary.json` include `replay` (`ageval.replay/1`): parent Attempt, lock digests, tool semantics, execution status (`matched`, `diverged`, or `error`), the comparator, and `first_divergence` when one exists. The field is omitted otherwise. Upload stores that object on the attempt row, so a missing parent archive does not erase it. Default pass@k and from-scratch rollups skip rows that carry `replay`, the same way they skip `fork`. Viewer and Hub show a replay marker and the divergence location. Replay completion is not a model-evaluation sample. The child ``trajectory.jsonl`` is the task text from the source trajectory plus each action executed in the fresh environment, with that execution's observation. It is not an empty file, and it does not copy the source model's usage.

---

## 3. Suite Execution, Always-k (`-k`), and Campaigns

| Execution Mode | CLI Command | Behavioral Contract |
| --- | --- | --- |
| **Single Attempt** | `ageval run <dataset> --task <id>` | Executes one task once and writes `.ageval/runs/<attempt_id>/`. |
| **Suite** | `ageval run <dataset>` (omitting `--task`) | Executes all member tasks in `<dataset>` and indexes the suite under `.ageval/suite-runs/<suite_run_id>/`. |
| **Always-k** | `ageval run <dataset> [-k N]` | Runs each selected task `N` independent times (`attempt_index = 0 .. N-1`). `-k` is a runtime CLI flag only, never a `task.yaml` field. |
| **Campaign** | `ageval campaign <dataset> --task a --task b --matrix ...` | Expands a Cartesian parameter grid across Trials without coupling to the internal control flow of `run.py`. |

```text
<dataset>/.ageval/suite-runs/<suite_run_id>/
├── summary.json       # Suite status, metrics.pass_rate, pass_at_k, pass_hat_k, task_refs[]
└── progress.json      # Planned slots, in-flight tasks, settled count, and cancellation state
```

While a suite is running, Core updates `summary.json` after each Attempt settles (`status: "running"` or `"cancelling"`) and writes the final settled summary when all slots finish or cancel. `ageval results upload-suite` accepts only terminal, complete suites. Suite resumption (`--resume-suite`, `--retry-errors`, `--replace-slot`) and `ageval results regrade` are specified in [01-core-lifecycle.md](01-core-lifecycle.md#5-suite-resumption-slot-replacement-and-regrade).

---

## 4. Post-Run Read-Only Analyzers (`stats`, `hack`, `review`)

After an Attempt is sealed, operators can run built-in **read-only analyzers** over `trajectory.jsonl`, `summary.json`, and the archived evidence directory (`src/ageval/evidence/analysis.py`):

```text
ageval results analyze <dataset> (--run <attempt_id> | --suite-run <suite_run_id>) [--analyzer stats|hack|review]
```

**Isolation invariant**: Analyzers execute strictly outside the four Attempt phases. They never invoke `bind_evaluation`, never mutate `result.json` or `evaluation/checks.json`, and their output reports remain local by default.

| Target Scope | Output File Path | Schema Format |
| --- | --- | --- |
| **Single Attempt** | `<dataset>/.ageval/runs/<attempt_id>/analysis/<analyzer>/report.json` | `ageval.analysis.report/1` |
| **Full Suite** | `<dataset>/.ageval/suite-runs/<suite_run_id>/analysis/<analyzer>/summary.json` | `ageval.analysis.summary/1` |

1. **`stats` (Deterministic Statistics, default)**: Computes `invoke_count`, `tool_call_count`, `tool_failure_count` / `tool_failure_rate`, `phase_timing`, `upstream_stall_count`, `repeated_tool_calls`, and `error_codes` locally without calling any LLM.
2. **`hack` (Two-Stage Reward Hacking Detector)**:
   - **Stage 1 (Rule screening)**: Scans `trajectory.jsonl` for five risk categories: `mutate_tests`, `read_gold`, `write_result`, `outbound_download`, and `other_llm`.
   - **Stage 2 (LLM verification, unless `--no-llm`)**: Sends up to 20 Stage 1 hit snippets to the `--agent` HTTP model (`openai-http` or `anthropic-http`), verifying that `evidence_quote` is an exact substring of the transcript. Zero Stage 1 hits immediately record `is_hack: false` (`decided_by: "stage1"`).
3. **`review` (Isolated Evidence Copy Audit)**: Copies the Attempt archive into a temporary directory and grants the `--agent` HTTP model read-only tools (`list_files`, `read_file`) plus `write_report` (requiring at least one file read before emitting structured `reward_hacking` and `task_specification` assessments). When `<attempt_dir>/analysis/<analyzer>/report.json` exists, `ageval view` exposes the **Analysis** tab on the Attempt detail view.
