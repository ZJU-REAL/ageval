# 08 — Hub, Registry Service, Agent Packages (`ageval.agent/1`), and Cloud-Hosted Jobs

This specification defines package and result publishing (`ageval publish`, `ageval plugin publish`, `ageval agent publish`, `ageval results upload-suite`), git-backed dataset registration (`eval_digest`), the Dataset Leaderboard and global Leaderboard Plaza (`/leaderboard`), **Agent packages** (`ageval.agent/1`) and the canonical models catalog, read-only snapshot shares (`/s/{token}`), and cloud-hosted evaluation jobs (`services/registry/hosted/`).

---

## 1. Git-Backed Dataset Registration and `eval_digest`

In addition to uploading full dataset tarballs, dataset owners can register a pinned git source via `ageval publish --repo github:org/repo@v1.0.0[#<subdir>]`, sending `{dataset_id, version, git_url, commit, eval_digest}` to `POST /v1/packages/{dataset_id}/source` without uploading archive bytes.

1. **URL security rules**: Registry accepts only userinfo-free `https://` URLs or `git@host:path` SSH locators. `file://`, `http://`, `ext::`, values starting with `-`, and URLs containing userinfo (`https://token@host`) are rejected before storage. `source-check` re-validates the URL and passes `--` before the URL in `git ls-remote`. Hub UI renders links only for URLs passing the same check, always pointing to the pinned commit SHA (`/tree/<sha>/<subdir>`, `/blob/<sha>/...`), never a mutable branch.
2. **`eval_digest` computation**: Computed locally during `lock` over all files that affect evaluation behavior: root `ageval.yaml` (excluding descriptive metadata such as `description`, and including `assets` entries by `path + sha256`), all member task files under `tasks/`, dataset-wide `shared/`, and the `prepare` script content. Root `README*` and `LICENSE` are excluded so documentation edits do not alter `eval_digest` (`package_digest` still hashes the full archive).
3. **Version conflict and result attribution (`bound_kind`)**: If `dataset_id@version` already exists with a different `eval_digest`, registration fails with `eval_digest_mismatch` (*"tasks changed, bump version"*); if `eval_digest` matches, the pinned commit SHA is updated in place. When `upload-suite` submits a suite whose `eval_digest` matches a registered release version, it is attributed (`bound_kind: "source"`) and checked for task completeness; otherwise it is stored as `bound_kind: "unknown"` and is ineligible for the public Leaderboard.

---

## 2. Dataset Leaderboard, Global Leaderboard Plaza (`/leaderboard`), and Inbox Approvals

Each Dataset detail page exposes two Leaderboard scopes:
- **Public**: Lists only suites that are (1) **complete** (all tasks settled), (2) bound to a published **release** version (not `draft`), and (3) approved by an owner of the dataset's organization (`board_listed: true`). Result `visibility: "public"` and `board_listed: true` are orthogonal flags.
- **Internal**: Visible to authorized organization members; includes incomplete or `draft`-bound suites.

Both Hub Dataset Leaderboards and local Viewer Suite views provide three switches: **Table** (default), **Pareto** (Pass rate vs. Cost / Tokens / Time frontier), and **Waffle** (`task × suite_run` trial grid).

### Global Leaderboard Plaza (`/leaderboard`) and Inbox (`pending` / `approved` / `rejected`)
The root Hub route `/` redirects to `/leaderboard`, indexing public evaluations across three views (`?view=dataset|agent|model`) without duplicating storage tables:

| View | Admission Rule | Grouping and Layout |
| --- | --- | --- |
| **Dataset** (default) | Public Dataset Leaderboard suites (`complete` + `release` + `board_listed: true`) | Grouped by Dataset (Table / Pareto / Waffle per group), backed by `GET /v1/results/suites?board=1`. |
| **Agent** (`?view=agent`) | Approved or auto-collected Agent Performance rows | Grouped by Agent organization (builtin short IDs in their own group), showing Agent, Dataset, Role, Model, Pass rate, and Mean score. |
| **Model** (`?view=model`) | Agent Performance rows uniquely joined to the canonical models catalog | Grouped by Model Lab, showing Model, Harness, Dataset, and Pass rate. |

Inbox manages two approval request types: `leaderboard_list` (approved by Dataset org owners) and `agent_performance` (approved by Agent package org owners, or platform maintainers `AGEVAL_REGISTRY_MAINTAINERS` for builtin short IDs).

---

## 3. Agent Packages (`ageval.agent/1`) and Canonical Models Catalog

An Agent package (`ageval.agent/1`) bundles a harness binding (`executor`, optional ACP `options.entry`, required `extensions`, and optional home configuration `overlays/`) with a default `model` block (`ModelSpec`). `base_url` and `api_key` store environment variable locators only.

| Category | Storage Location | Resolution and Publishing Rules |
| --- | --- | --- |
| **1. Builtin Agent Packages** (`builtin: true`, no `org_id`) | `src/ageval/agents/builtin/catalog.json` and sibling package trees (`src/ageval/agents/reserved.py`) | Resolved directly by CLI `--agent <short_id>` and Hub `/agents` without `ageval agent install`. Reserved short IDs:<br>• **ACP entries**: `pi`, `opencode`, `codex`, `claude-code`, `grok-build`<br>• **HTTP executors**: `openai-http`, `anthropic-http`<br>Environment kinds (`docker`, `local`, etc.) are never Agent packages. |
| **2. Custom Agent Packages** (`org/name@version`) | `examples/agents/*` (`dsh-default`, `nooa-default`, `miniswe-default`, `terminus-2-default`, `openhands-default`) or published via `ageval agent publish` | Installed into `~/.ageval/agents` via `ageval agent install <ref>` (which also installs non-builtin plugins in `binding.extensions`). |

- **CLI flags**: `--agent` and `--profiles` are mutually exclusive; `--model <model_id>` requires `--agent` and overrides `model.id` on bound role profiles.
- **Provenance (`agent_ref`) and Offline Models Catalog**: `agent_ref` is stored in Registry's `job_overlay` without altering `lock.json`. Maintainers generate a versioned in-repo models catalog snapshot (`scripts/sync_model_pin.py`) with canonical IDs, vendored Lab SVGs, modalities, context windows, and reference pricing (used only for `cost_usd_estimated`). Raw `model.id` strings join to a canonical model entry only when exact alias matching or longest-first suffix matching (after stripping known gateway prefixes) yields a **unique** match.

---

## 4. Snapshot Shares (`/s/{token}`)

Operators can generate anonymous read-only share links (`/s/{token}`) for a local suite or single Attempt via `ageval results share-snapshot`:
- **`static` mode (default)**: Freezes the suite summary and Attempt archives uploaded at creation time.
- **`live` mode (`--live`)**: Writes `.ageval/suite-runs/<id>/live-share.json` and pushes incremental `PATCH /v1/shares/{token}` updates as child Attempts settle (or via `ageval results sync-snapshot`).
- **Isolation and revocation**: Stored in dedicated `snapshot_shares` tables and `shares/` blob prefixes without changing `visibility` or `board_listed`. Owners can revoke links at any time via `ageval results revoke-snapshot <token-or-url>`.

---

## 5. Cloud-Hosted Evaluation Jobs (`services/registry/hosted/`)

Authenticated organization members can submit a dataset evaluation job from Hub (`POST /v1/hosted/jobs`). An out-of-process background worker (`python -m services.registry.hosted.worker`) claims `queued` jobs (`queued → running → succeeded | failed | canceled`), runs `ageval run` inside a cloud sandbox (**`e2b`** or **`daytona`** only; other environments fail with `hosted_environment_refused`), and uploads the resulting suite and Attempt archives (`visibility="private"`).

### Organization secrets (`hosted_secrets`)
Secrets receive plaintext once on `POST /v1/orgs/{org_id}/secrets` and are encrypted at rest using `AGEVAL_HOSTED_SECRET_KEY` (32-byte URL-safe base64 master key) via authenticated stream encryption (HMAC-SHA256). List and job endpoints return metadata only:
- **`kind="model"`**: Inference API key locator matching `^[A-Z][A-Z0-9_]{0,63}$` and ending in `_API_KEY`, `_KEY`, or `_TOKEN` (excluding `E2B_API_KEY` and `DAYTONA_API_KEY`). Written as `${LOCATOR}` in the generated `profiles.yaml`.
- **`kind="provider"`**: Cloud sandbox provider key (`E2B_API_KEY` or `DAYTONA_API_KEY` matching `environment`), projected only into the worker's host subprocess environment and never into the sandbox or evidence archive.
