# ageval CLI

This package directory implements the public `ageval` console script (`main.py`).  
The CLI only maps argv → application use cases → stdout / stderr / exit codes. It does **not** own Config merge, digests, or PASS.

Deeper diagnostics and Result fields: `skills/ageval-cli/`.  
Registry service ops: `services/registry/README.md`.

## Install

From the repository root:

```bash
uv sync
uv run ageval --help
# short form for help (standard):
uv run ageval -h

# package version (capital -V; -v is often verbose on subcommands):
uv run ageval -V
uv run ageval --version

# when talking to a Postgres/S3-backed Registry process:
uv sync --extra registry
```

## Conventions

| Item | Meaning |
| --- | --- |
| Dataset path | Root with `ageval.yaml` (`ageval.dataset/1`) |
| Registry ref | `<dataset_id>@<version>` or `<dataset_id>@sha256:<64hex>` |
| `--task` | Member `task_id` under `tasks/<id>/task.yaml` |
| Success output | Most commands print **one JSON object** on stdout (`sort_keys`) |
| Failure | Human message on stderr + stable `error_code`; often exit **2** |
| Secrets | Never written into lock / evidence; Registry uses `~/.ageval/credentials` or env |

### Global flags

| Flag | Meaning |
| --- | --- |
| `-h`, `--help` | Show help (root or any subcommand). **`-h`**, not `-H`, is the usual short form. |
| `-V`, `--version` | Print package version and exit. Capital **`-V`** avoids clashing with `-v` (verbose). |

### Exit codes (`ageval run` / `campaign`)

| Code | Meaning |
| --- | --- |
| `0` | PASS |
| `1` | FAIL (evaluator) |
| `2` | ERROR / config / runtime |

Other subcommands: `0` on success, typically `2` on operator error.

### Common environment variables

| Variable | Role |
| --- | --- |
| `AGEVAL_REGISTRY_URL` | Registry base URL |
| `AGEVAL_REGISTRY_TOKEN` | Bearer token (CI; overrides file token) |
| `AGEVAL_RESULTS_URL` | Results store URL (defaults to Registry URL) |
| `AGEVAL_CACHE_ROOT` | Local verified cache root (default `.ageval/cache`) |
| `AGEVAL_OFFLINE_AGENT` | Set to `1` for fail-closed agent path (offline tests) |

Credentials file `~/.ageval/credentials` (mode `0600`):

```json
{
  "registry": {
    "url": "http://127.0.0.1:8700",
    "token": "…"
  }
}
```

---

## Command map

| Command | Purpose |
| --- | --- |
| `ageval tasks` | List member task ids in a Dataset |
| `ageval lock` | Lock config (no Agent) |
| `ageval run` | Run one member or a full suite (Always-k via `-k` / `--n-attempts`; `--keep-workspace` keeps the host work root, not Docker volumes) |
| `ageval campaign` | Serial parameter-matrix campaign (matrix axis ≠ k-attempt) |
| `ageval executors` | Host executor / ACP entry inventory |
| `ageval plugin install\|list\|uninstall` | Local `ageval.plugin/1` cache (`$AGEVAL_HOME/plugins`); never rewrites profiles |
| `ageval plugin publish` | Upload a plugin package (`package_kind=plugin`); optional `--replace` |
| `ageval evidence` | Export sealed trajectory copy (does not change score) |
| `ageval submit` / `status` / `cancel` | Durable Run / suite job control (suite id + optional `--dataset`) |
| `ageval login` | GitHub **Device Flow** → write credentials (Hub uses browser OAuth instead) |
| `ageval publish` | Publish a Dataset package (**requires `--org`**); `--draft` overwrites the draft slot; optional `--replace` |
| `ageval release` | Owner: promote the current dataset draft to an immutable version |
| `ageval registry list\|show` | Browse remote packages |
| `ageval registry delete\|set-visibility` | Owner ops on `dataset_id@version` (org owner; delete needs `--yes`) |
| `ageval registry org-create\|org-list` | Create / list organizations (packages belong to orgs) |
| `ageval registry org-add-member\|org-remove-member` | Add / remove org members by GitHub login (owner or admin; target need not be logged in) |
| `ageval registry org-set-role\|org-transfer` | Change an existing member's role, or hand the org to a current member (caller becomes member) |
| `ageval cache list\|path\|purge` | Local verified cache |
| `ageval results upload\|get\|list` | Attempt run evidence bundles; upload accepts `--replace` |
| `ageval results upload-suite\|get-suite\|list-suites` | Suite/job aggregates + task refs (no suite PASS); meta may include `job_overlay` |
| `ageval results export-profiles` | Export suite `job_overlay` → re-runnable `profiles.yaml` (#59) |
| `ageval results share\|unshare` | Share / revoke private result access (owner only) |
| `ageval results delete\|set-visibility` | Delete or flip visibility (`--kind attempt\|suite`; delete needs `--yes`) |
| `ageval view` | Local Dataset Web UI (no Registry). `--dev` starts API and Vite when possible; `--open` deep-links a job/task/run |
| `ageval jobs delete` | Delete a local Job under `--local` (suite always cascades Attempts). Requires `--yes` |

Discover flags with `uv run ageval <cmd> -h`.

---

## Local path workflow (no Registry)

```bash
uv run ageval tasks examples/core

# Local Web UI: Jobs → Tasks → Trial (suite-runs under .ageval/; no Registry)
uv run ageval view examples/core
# uv run ageval view tests/fixtures/datasets/suite-min --port 8765 --no-browser
# uv run ageval view examples/core --dev --open /jobs/<id>
# Preview local delete, then confirm (suite cascades Attempts; not Registry)
# uv run ageval jobs delete --local examples/core --job <id>
# uv run ageval jobs delete --local examples/core --job <id> --yes

uv run ageval lock examples/core --task config-minimal

uv run ageval run examples/core --task sdk-agent-session

# Full suite (omit --task)
uv run ageval run examples/core

# Always-k (#47): k independent Attempts per task — CLI/job only (not task.yaml)
uv run ageval run examples/core -k 5 --max-concurrent-tasks 2
uv run ageval run examples/core --task sdk-agent-session -k 5
# Resume / top-up: skip real finished units; re-run suite-cancel placeholders; recompute pass@k
# uv run ageval run examples/core --resume-suite <suite_run_id> --task sdk-agent-session -k 5
# Replace one finished slot (new Attempt; old current → previous[]):
# uv run ageval run examples/core --resume-suite <suite_run_id> --task sdk-agent-session --replace-slot

# Allowlisted --set (JSON Pointer = JSON value)
uv run ageval lock examples/core --task config-minimal --set /parameters/seed=7
# Job binding override: entry/model/plugin options live in profiles.yaml, not task.yaml
uv run ageval run examples/core --task sdk-agent-session \
  --set '/bindings/solver/options/entry="pi"'
# Or replace Dataset profiles.yaml for the run:
# uv run ageval run examples/core --task sdk-agent-session --profiles /path/to/profiles.yaml
```

### Allowlisted `--set` pointers

Fixed parameter leaves (others fail closed):

- `/parameters/seed`
- `/parameters/active_profile`

Job binding axes:

- `/bindings/<role_id>/model`
- `/bindings/<role_id>/executor`
- `/bindings/<role_id>/api_key`
- `/bindings/<role_id>/base_url`
- `/bindings/<role_id>/options/<key>` (executor plugin row; ACP still rejects `command` / engine keys)

**Not** overridable: intent `limits.*` (task contract).

String values need JSON quotes, e.g. `--set '/bindings/solver/options/entry="pi"'`.

### Evidence and trajectory

`ageval run` JSON often includes **`logs`**: Attempt evidence root.

```bash
uv run ageval evidence "$LOGS_PATH" --out /tmp/ageval-export
```

Trajectory presence **≠** PASS. PASS comes only from an independent evaluator.

### Always-k metrics (suite job)

After `-k` / full suite, read:

```text
.ageval/suite-runs/<suite_run_id>/summary.json   # metrics.pass_at_k / pass_power_k / pass_rate …
.ageval/suite-runs/<suite_run_id>/progress.json
```

- **pass@k** / **pass^k** are **job** aggregates (mean over tasks); not package identity  
- `--max-concurrent-tasks` only speeds scheduling; does not change k or PASS  
- Single-task `k=1` without `--resume-suite` keeps the historical single Attempt JSON on stdout  

### Campaign / control plane (brief)

```bash
uv run ageval campaign examples/core --task config-minimal \
  --matrix '/parameters/seed=[1,2,3]'

uv run ageval submit examples/core --task config-minimal
uv run ageval status <run_id>
uv run ageval cancel <run_id>

# Suite job (#47 D)
uv run ageval status <suite_run_id> --dataset examples/core
uv run ageval cancel <suite_run_id> --dataset examples/core
```

### Executors

```bash
uv run ageval executors      # JSON: supported / host_ready / acp_entries / bake_recipe_declared
uv run ageval executors -v   # --verbose: credential env names and extra detail
uv run ageval lock examples/core --task config-minimal --probe
# --probe: plan + readiness for this binding / provider.kind; no Agent, no bake
```

Coding-agent packages use `executor: acp` + `- plugin: acp` / `options.entry: …`. Prefer inventory output over hardcoded vendor lists.

---

## Registry workflow (optional service)

```bash
docker compose -f services/registry/docker-compose.yml up -d --build
export AGEVAL_REGISTRY_URL=http://127.0.0.1:8080
```

### Login, org, and publish

Packages **must** belong to an organization (`--org`). Results belong to the
uploader and can later be shared to an org or user.

```bash
# Interactive GitHub Device Flow (server needs AGEVAL_GITHUB_CLIENT_ID/SECRET)
uv run ageval login

# CI: no browser
export AGEVAL_REGISTRY_TOKEN=<bootstrap-or-ci-token>

uv run ageval registry org-create my-lab --display-name "My Lab"
uv run ageval registry org-list
# Official slug (default `official`) is reserved: admin bootstrap token only.
# uv run ageval registry org-create official
# uv run ageval registry org-add-member official alice --role owner
# uv run ageval registry org-set-role official alice --role owner
# uv run ageval registry org-transfer official alice
# uv run ageval registry org-remove-member official alice

# Default visibility private; explicit public. --org is required.
uv run ageval publish tests/fixtures/datasets/publish-min --org my-lab
uv run ageval publish path/to/db --org my-lab --draft
uv run ageval release my-org/dataset
uv run ageval publish path/to/db --org my-lab --public
# Same dataset_id@version → 409 unless org owner passes --replace (rewrites blob/digests/visibility):
# uv run ageval publish path/to/db --org my-lab --replace
# Public Leaderboard lists complete, release-bound suite uploads only.
# Draft-bound / incomplete suites stay on Task Jobs.
```

### Lock / run by ref

```bash
uv run ageval lock 'test/publish-min@0.1.0' --task hello
uv run ageval run  'test/publish-min@0.1.0' --task hello
uv run ageval lock 'test/publish-min@sha256:…' --task hello
```

### Catalog and cache

```bash
uv run ageval registry list
uv run ageval registry list --prefix test/
uv run ageval registry show 'test/publish-min@0.1.0'
# Org owner (or admin): flip visibility after publish; delete requires --yes
uv run ageval registry set-visibility 'test/publish-min@0.1.0' --visibility public
# uv run ageval registry delete 'test/publish-min@0.1.0' --yes

uv run ageval cache list
uv run ageval cache path 'test/publish-min@sha256:…'
uv run ageval cache purge all --yes   # destructive; requires --yes
```

### Attempt results

Upload sealed trees under `<dataset>/.ageval/runs/<run_id>/` (not package releases).

```bash
uv run ageval results upload /path/to/dataset --run <run_id>
# Same run_id → 409 unless owner passes --replace (rewrites archive + meta):
# uv run ageval results upload /path/to/dataset --run <run_id> --replace
uv run ageval results list --dataset-id test/publish-min
uv run ageval results get <run_id> --out /tmp/restored-run
uv run ageval results set-visibility <run_id> --kind attempt --visibility public
# Share / unshare a private result (owner only):
uv run ageval results share <run_id> --kind attempt --share-org my-lab
uv run ageval results unshare <run_id> --kind attempt --share-org my-lab
# uv run ageval results delete <run_id> --kind attempt --yes
```

Visibility is **public** or **private** only. Packages are owned by an **org**;
results are owned by the **uploader** (`uploaded_by`). Private results stay
invisible to org members until the owner shares them. Default private; `--public`
for public at create time, or `set-visibility` later.

### Suite / job results

After `ageval run <dataset>` (full suite or Always-k), summary lives at
`<dataset>/.ageval/suite-runs/<suite_run_id>/summary.json` with observational
`metrics.pass_rate` / `mean_score` / `pass_at_k` / `pass_power_k` (not suite PASS).

**Metrics contract (upload / Registry, #60):**

| Path | Shape |
| --- | --- |
| `metrics.pass_at_k["<k>"]` | `{ value, n_tasks, incomplete_tasks }` (k as string key) |
| `metrics.pass_power_k["<k>"]` | same |
| `metrics.n_attempts` / `k_values` / `per_task` | job sample budget, k list, per-task n/c audit |
| `task_refs[]` | `task_id`, `status`, `score`, `run_id`; multi-attempt may add `n`, `c`, `attempt_run_ids`; replaced slots add `previous[]` |

`upload-suite` **recomputes** missing k maps locally from `attempts[]` or task
`n`/`c` before POST. Registry stores the full `metrics` blob (no strip).
pass@k is **not** a `config_fingerprint` / job-identity key.
Public Leaderboard lists only **complete**, **release-bound** suites; incomplete
or draft-bound rows stay on Task Jobs.

```bash
uv run ageval results upload-suite /path/to/dataset --suite-run <suite_run_id> \
  --agent codex --model gpt-test
# Optional full Attempt evidence (Hub Jobs deep-link / evidence browser):
uv run ageval results upload-suite /path/to/dataset --suite-run <suite_run_id> \
  --with-attempts
# Owner overwrite of same suite_run_id (default is 409; no history):
# uv run ageval results upload-suite … --suite-run <id> --replace
# Patch one slot onto an already-uploaded suite (new Attempt + previous[]):
# uv run ageval results upload-suite … --suite-run <id> --task <task_id> [--run <run_id>] --with-attempts
# Or backfill one run later:
uv run ageval results upload /path/to/dataset --run <run_id>
uv run ageval results list-suites --dataset-id test/suite-min
uv run ageval results get-suite <suite_run_id> --out /tmp/restored-suite
uv run ageval results set-visibility <suite_run_id> --kind suite --visibility private
# Delete suite meta only (attempts remain); cascade with --with-attempts:
# uv run ageval results delete <suite_run_id> --kind suite --yes
# uv run ageval results delete <suite_run_id> --kind suite --with-attempts --yes
# No registry: fall back to local suite-runs
uv run ageval results list-suites --local /path/to/dataset
uv run ageval results get-suite <suite_run_id> --local /path/to/dataset
```

**`--with-attempts` (issue #43 / #60):** after the suite summary archive uploads,
each run id from `task_refs[].attempt_run_ids` (preferred) or `task_refs[].run_id`
is packed from `.ageval/runs/<run_id>/` with the **same visibility** as the suite.
Missing local run dirs **fail closed** before any network upload. Re-uploading an
existing `run_id` without `--replace` is treated as success (`already_exists`).
With suite `--replace`, linked attempt uploads also replace. Registry suite list/get
annotate each task_ref with `has_attempt_content` so Hub Jobs can open evidence or
show “Not uploaded”.

---

## Suggested smokes

| Goal | Command |
| --- | --- |
| CLI works | `uv run ageval -h` / `uv run ageval -V` |
| List tasks | `uv run ageval tasks examples/core` |
| Lock only | `uv run ageval lock examples/core --task config-minimal` |
| Local agent | `uv run ageval run examples/core --task sdk-agent-session` |
| Registry (service up) | `publish` → wipe `AGEVAL_CACHE_ROOT` → `lock <ref> --task …` |

Example packages and evidence grades: `examples/README.md`, root `Agents.md`.

---

## Implementation boundary

| Layer | Owns |
| --- | --- |
| `cli/main.py` | Typer routes, JSON printing, exit codes |
| `application/*` | Use cases (lock / run / publish / login / …) |
| Config / Core | Spec load, lifecycle, PASS |
| `services/registry` | Standalone HTTP service; CLI is HTTP client only |

New commands: thin wrapper in `main.py`, logic in `application/`, update this README and `skills/ageval-cli` when the public surface changes.
