# CLI command notes

Box kind is `environment:` on the profiles document. `--probe` is `ageval run --probe` (lock + preflight). Dataset root. `submit` does not exist. Trust `uv run ageval --help`.

## `ageval registry`

- `list` / `show <id@version|@sha256:…>`: visible releases; `show` prints digest / size / visibility
- Org ops (`org-create` / `org-add-member` / `org-set-role` / `org-transfer` / `org-remove-member`): owner or admin; the last owner cannot leave or be demoted
- `set-visibility <id@version> --visibility public|private`: owner or admin
- `set-description <org/name> --description '…'`: marketplace description override, no republish; empty string clears the override (falls back to the package manifest description). Server enforces org owner
- `delete <id@version> --yes`: owner or admin

## `ageval executors`

Two product facts (+ ACP entry inventory):

1. **What ageval supports** — `agent_profiles[].executor` kinds on this install
2. **What the host can run** — binaries / ACP entries ready (no secrets)

Stdout JSON (high level):

| Key | Meaning |
| --- | --- |
| `supported` | Kind names valid for `agent_profiles[].executor` (e.g. `acp`, `openai-http`, `anthropic-http`) |
| `host_ready` | Subset of kinds that can be constructed on this host |
| `executors[]` | Per kind: `execution_mode` (from `describe()` when published), `host_ready` |
| `acp_entries[]` | Per ACP `entry_id`: `acp_command`, `engine_ready`, `acp_entry_ready`, `host_ready`, credential env *names*; `-v` adds `credential_missing` / `keyless_auth` |

- ACP registry: `ageval.plugins.contrib.acp.registry` (static pins)
- Plugin `host_ready` uses declared `host_requires` / reachable `describe()`
- Child env is allowlisted (`PATH` / `HOME` / `LANG` + entry credential names + binding locators + `fixed_env`). Undeclared host tokens do not reach the entry
- No package path; no secrets; exit 0

**Author packages with:** `executor: acp` + `- plugin: acp` / `options.entry: <entry_id from acp_entries>`.

## `ageval lock`

- Deterministic JSON on stdout (digest, `dataset_id`, task_id, resolution). No `database_id`.
- No secret values.
- Does not create Run/Attempt or start Agent.
- Rejects unknown format (`invalid_format` at `/format`), unknown `executor` kinds, and ACP profiles missing `- plugin: acp` / `options.entry`.
- `--probe` on **run** (not a second lock mode that starts an environment): lock plus observational readiness. Exit non-zero when the selected `environment` path is unsatisfied. Checks declared `host_requires`, Docker daemon when kind is docker, locator **names** (never values). ACP entries add `credential_missing` (if the entry requires a key, the check fails and the run does not start; warning-only when `keyless_auth`). HTTP executors report `credential_missing` only when the locked `base_url` is not loopback. `AGEVAL_OFFLINE_AGENT=1` is reported; probe still does not spawn.

## `ageval run`

- `--probe` (requires `--task`): same feasibility report; does not start an Attempt.
- TTY: short recap on stdout (per-task PASS/FAIL, `summary` / `logs`, `ageval view` next). Full document stays on disk. `--json` or a non-TTY stdout keeps one JSON object.
- One foreground Attempt via production composition root **when** `--task` is set, `-k` defaults to 1, and no `--resume-suite`.
- Evidence under dataset root `.ageval/runs/<id>/`. `logs` / `evidence_path` are portable relative to the dataset root.
- **Always-k** (`--n-attempts` / `-k`, integer ≥1): fixed k independent Attempts per task. CLI/job only — not `task.yaml`.
- **Suite**: omit `--task` → all members.
- **`--max-concurrent-tasks`**: speeds wall time only; does not change k or PASS.
- **`--resume-suite` / `--replace-slot` / `--attempt-index`**: suite resume; see `ageval run --help`.
- **`--keep-workspace`**: after cleanup, do not delete the box work root (host residual may still be named `l1-work/` — historical directory name, not an isolation tier). Default off. Docker volumes are still removed. Upload packs never include `l1-work/**`.
- **`--keep-vendor-raw`**: after a successful trajectory seal, keep invocation `backend_raw/` / layer B (`request.json`, `events.jsonl`, `final-response.json`, `metadata.json`) and `evaluation/evaluator_raw.json`. Default off: those files are dropped; Hub archives skip them even if residuals remain. `evaluation/observation.jsonl` (evaluate-phase SDK invoke) and `evaluation/checks.json` (evaluator `checks`) are **kept** either way. Independent of `--keep-workspace`.
- `--profiles` replaces the dataset job document. `--agent` and `--profiles` are mutually exclusive. `--agent pi` resolves the shipped catalog tree (no install). `--model` requires `--agent` and writes this run’s overlay model; omit it to keep the package default. Not `ageval results --model`.
- `--dir <path>`: only with a registry ref. Looks at `<path>/<dataset_id>/` (example: `--dir tmp` + `official/demo@0.1.0` → `tmp/official/demo`). Reuse that child if it already matches; otherwise fetch into it and run. Relative paths are from cwd. Local path + `--dir` is `invalid_override`.
- Per invocation: Core writes `trajectory.jsonl` (`ageval.trajectory.event/1`) for **run-phase** Agent turns. Evaluate-phase SDK invoke (LLM-as-judge) writes `evaluation/observation.jsonl` instead. Neither file is PASS.
- Docker kind uses the docker environment winner + `attach_stdio`; coding entries stay on the parent ACP client.

## `ageval evidence`

- Read-only export of **sealed** invocations.
- Refuses unsealed (running) metadata.
- Does not change evaluation score.

## `ageval campaign`

- Foreground serial matrix; allowlisted `/parameters/*` axes.
- Not a parallel scheduler. Does not merge with `run.py` inner loops.

## Control surface

- `status` / `cancel` operate on ControlStore records.
- Suite jobs may take `--dataset` to read `progress.json` or write `cancel.requested`.
- There is no `submit`.

## Always-k vs campaign

- **Always-k** (`ageval run -k`): repeat independent Attempts for pass@k samples.
- **Campaign** (`ageval campaign --matrix`): sweep allowlisted parameters / bindings on one task.

## `ageval results upload` / `upload-suite`

- Single Attempt upload does **not** create a suite Leaderboard row.
- Prefer `upload-suite` after `ageval run <dataset>` **without** `--task`.
- Dataset arg is a path or registry ref (`id@version`); a unique verified cache hit does not contact Hub to find the local suite-runs.
- Hub Leaderboard **Public** lists complete, release-bound suites only.

### Hub path checklist

```text
ageval publish <dataset> --org <org> --draft
ageval release <org/dataset>
ageval run <dataset> [--profiles …]          # omit --task → suite
ageval results upload-suite <dataset> --suite-run <8-hex> --public [--with-attempts]
```

## `ageval publish` / `ageval release`

- Draft slot overwrites for that `dataset_id`. Reserved version name `draft` is not a release.
- `ageval release <dataset_id>` promotes the current draft.
- Plugin packages do **not** use the draft slot.

## `ageval view` / `ageval jobs delete`

- Local UI. A dataset root or registry ref (`id@version` / `@sha256:…`) opens that one package. A directory that is not a dataset root lists immediate children whose `ageval.yaml` is `ageval.dataset/1` and skips the rest. A unique verified cache hit does not contact Hub.
- Header: Datasets, Jobs, Agents, Plugins. More than one dataset lands on Datasets; one lands on Jobs. Jobs are only that package's `.ageval/suite-runs/` and `.ageval/runs/`.
- Agents and Plugins are read-only: builtin packages from this CLI, plus `$AGEVAL_HOME/agents` and `$AGEVAL_HOME/plugins` index rows. No install, uninstall, or yaml edit from the page.
- `jobs delete --local <dataset> --job <id> --yes` is local Job delete, not Registry `results delete`.
