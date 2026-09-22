# ageval Viewer — Agent constraints

This directory is the **local dataset / suite-results Web UI**.
Python serves the built SPA; React app lives here.

## Authority

| Doc | Role |
| --- | --- |
| [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md) | Visual constitution (tokens, focus, motion) |
| [`apps/shared/DESIGN.md`](../shared/DESIGN.md) | SPA token YAML (Hub/Viewer share it) |
| [DESIGN.md](./DESIGN.md) | Taste (anti-slop) + which component to reuse |
| This file | Product scope + stack + API |
| `src/ageval/viewer/` | HTTP API + static file serving (stdlib) |

When UI conflicts with taste: **docs/13** for language; **DESIGN.md Taste** for
anti-slop; **DESIGN.md** role table for which control. Evidence tabs use
`UnderlineTabs`. Jobs/tasks stay tables.

## Product surface (scope lock)

`ageval view` takes a dataset root, a registry ref, or a directory that is not
itself a dataset. A non-dataset directory is scanned **one level**: children
whose `ageval.yaml` is `ageval.dataset/1` are opened; everything else is
skipped. The server still starts when that list is empty.

Header destinations, same chrome either way: **Datasets**, **Jobs**, **Agents**,
**Plugins**. No sidebar. Lists are tables, not catalog cards. Dataset choice on
Jobs is a Select.

Landing: more than one dataset → Datasets. Exactly one (including
`ageval view <dataset>`) → Jobs. The Datasets table still lists that one row.
`--open` wins over the landing.

**In scope:**

1. **Datasets** — one row per opened package, grouped by the organization in
   `dataset_id`. Display `dataset_id@version`. The switch key is the directory
   name (two siblings may share `dataset_id`). Opening a row is read-only:
   README when present, `ageval.yaml`, `profiles.yaml` when present, and a
   file tree with a size-capped preview. `.ageval/runs` and `.ageval/suite-runs`
   are not on that tree.
2. **Jobs list** — search; filter dropdowns; sortable columns; row click.
   Jobs = that package's `.ageval/suite-runs/` and `.ageval/runs/` only.
   Routes carry the directory key so two packages cannot share a `job_id`.
3. **Job → tasks** — task table with scores / status / agent-model meta
4. **Task detail** — trials/run row(s), status/error coloring, **copyable CLI**
5. **Attempt / trial detail** — `Jobs > job > task > run_id`; Outcome + actors
   (Role / Harness / Model / Time / Usage) + tabs from real evidence only
   (Trajectory · Agent · Verifier · Artifacts · Lock · Runtime). Top bar may show
   framework / environment kind / `provenance.upstream.url`. Multi-role groups Trajectory
   and Agent tree by `profile_id`. Usage/trajectory are observational ≠ PASS.
6. **Breadcrumb** — `Jobs > jobId > taskId > runId` with `>` separators; click to navigate
7. **Delete a local Job** — Jobs row menu or bulk selection. Preview paths /
   bytes / cascade `run_id`s, then confirm. Suite delete always removes
   referenced Attempts. No delete control on an inner trial. Does not call
   Registry. Deletes only under the selected dataset root. Same Application
   use case as `ageval jobs delete --local … --yes`.
8. **Pin / note (this browser)** — `localStorage` keyed by `dataset_id` +
   `job_id`. Not written to evidence, lock, or Registry. Pinned rows sort
   first. Action icon (always on): note, else pin, else hover settings.
   Hover a note icon to read the note.
   Click the settings/note control to open the menu (do not open on hover).
9. **Plugins** — rows from `$AGEVAL_HOME/plugins` `index.json` `(id, version)`
   plus first-party contrib short ids from this CLI, marked built-in.
   Read-only: README when present, `plugin.yaml`, declared slots, file tree,
   size-capped preview. The table shows description; source stays a filter.
10. **Agents** — same for `$AGEVAL_HOME/agents` and the builtin Agent catalog
    (`agent.yaml`).

**Out of scope unless user asks:**

- Public catalog, OAuth, Postgres, Leaderboard SPA (#22)
- Hub / Registry write (publish, upload, release, remote delete)
- Viewer sidebar, catalog-card lists, install / uninstall / editing yaml
- Scanning more than one directory level, opening `$AGEVAL_HOME` as a file tree,
  reading `credentials`, or merging the cwd Registry cache into Datasets
- Scanning the git checkout `plugins/` tree (builtins come from the running CLI)
- A gold tab. `tasks/*/evaluation/` may appear as ordinary package files
- Marketing mesh gradients, dark neon skins, custom CSS component kits
- Fabricating Harbor-only files or empty evidence tabs
- Soft-delete trash, live cancel, `l1-work` cleanup, deleting one Attempt inside a suite

## Stack (mandatory)

| Layer | Choice |
| --- | --- |
| Build | Vite + React + TypeScript |
| Package manager | **pnpm** only (`packageManager` field; not npm/yarn) |
| Styling | Tailwind CSS v4 (or v3 if tooling forces) |
| Components | **shadcn/ui** (Radix primitives) — overlap under `apps/shared/components/ui/` |
| Icons | lucide-react (shadcn default) — one family only |
| Table | shadcn Table patterns (sortable heads in-app) |
| Routing | react-router-dom (client routes under SPA) |
| Fonts | Geist if vendored; else Inter + system mono |

**Forbidden:**

- Hand-rolled full CSS design system replacing shadcn
- Second component library (MUI, Ant, Chakra, Bootstrap)
- Inline style soup for layout chrome
- Google Fonts CDN in production (prefer self-host / system stack)

## Design discipline

1. Read [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md)
   and [DESIGN.md](./DESIGN.md) (**Taste** + role table) before changing
   colors, type, or density.
2. Do not describe or invent page layout in this file. Copy a shipped control.
3. **Tabular nums** for scores, rates, durations, trial fractions.
4. Mono **only** for commands, digests, technical IDs.
5. No em-dash (`—`) in UI strings. No `uppercase tracking` section eyebrows.
6. Prefer density of a results console, not an art gallery landing page.
7. Semantic tokens only. No `slate-` / `zinc-` / `gray-` utilities.

## UI reuse (mandatory)

Same stack as Hub: overlap primitives in `apps/shared/components/ui/`. Role → component:
[DESIGN.md](./DESIGN.md).

1. **Copy an existing instance**, including focus classes. Version / filter /
   action lists go through `@ageval/shared/components/ui/select` or
   `@ageval/shared/components/ui/dropdown-menu`. Match Hub `VersionSwitcher` (label +
   trailing date on `SelectItem`).
2. **No native `<select>` / `<option>`** and no hand-rolled dropdown for
   product chrome. If the primitive is missing a slot (e.g. `trailing`),
   extend `apps/shared/components/ui/select.tsx` so Hub and Viewer stay aligned.
3. **Scan vs edit focus** (docs/13): Jobs search keeps `hairline` on focus.
   Do not accept `Input`'s default `border-link` for a new search.
4. Operator-facing list text is a short label plus time. Slot history:
   `patch N` + `formatDate` / `formatDay`. Do **not** put `run_id` or sha256
   in the trigger or the menu. Digests stay on the trial heading / breadcrumb.
5. Do not add a second component library or a one-off styled native control.

## Backend contract

Python API under `/api/*` (see `src/ageval/viewer/`):

| Path | Purpose |
| --- | --- |
| `GET /api/health` | Liveness |
| `GET /api/session` | Opened datasets, landing (`jobs` when exactly one, else `datasets`) |
| `GET /api/datasets` | Dataset rows (`key` = directory name, label `dataset_id@version`) |
| `GET /api/datasets/{key}` | README / manifest / profiles names for that package |
| `GET /api/datasets/{key}/tree` | Package file tree. Omits `.ageval/runs` and `.ageval/suite-runs` |
| `GET /api/datasets/{key}/file?path=` | Size-capped preview. Refuses `..`, `credentials`, and paths outside the root |
| `GET /api/plugins` | Builtin contrib rows plus `$AGEVAL_HOME/plugins` index rows |
| `GET /api/plugins/package?source=&id=&version=` | Plugin package names (README, `plugin.yaml`) |
| `GET /api/plugins/tree` | Same query. Tree confined to that package root |
| `GET /api/plugins/file?path=` | Preview. Same refusal rules |
| `GET /api/agents` | Builtin catalog plus `$AGEVAL_HOME/agents` index rows |
| `GET /api/agents/package` | Agent package names (README, `agent.yaml`) |
| `GET /api/agents/tree` | Tree confined to that package root |
| `GET /api/agents/file?path=` | Preview. Same refusal rules |
| `GET /api/jobs?dataset=` | Job list for that directory key. Omitted when exactly one dataset is open |
| `GET /api/jobs/{id}` | Job detail + task rows |
| `GET /api/jobs/{id}/delete-preview` | Paths, bytes, cascade run ids, confirm token; refuse reasons |
| `DELETE /api/jobs/{id}?confirm=` | Hard-delete after preview token (suite cascades Attempts) |
| `GET /api/jobs/{id}/tasks/{task_id}` | Task detail + enriched trials list + commands |
| `GET /api/jobs/{id}/tasks/{task_id}/trials` | Trials list (suite + local evidence) |
| `GET /api/jobs/{id}/tasks/{task_id}/trials/{run_id}` | Attempt meta + `available_tabs` |
| `GET .../trials/{run_id}/tree?scope=` | File tree under evidence (`agent`/`verifier`/`runtime`/…) |
| `GET .../trials/{run_id}/file?path=` | File preview (size-capped; secret-like names redacted) |
| `GET .../trials/{run_id}/trajectory` | Parsed `trajectory.jsonl` steps (observational) |

Trial meta returns `framework` / `docker` / `upstream_url` (and related provenance
fields) plus `actors[]` from lock + invocation metadata: role · agent · model ·
Time (`time_label` / `latency_ms_sum`) · Usage (`usage_label` / normalized last-inv
usage). Cache hit rate uses inclusion/disjoint heuristics; never treat
`UsageUpdate.used` as billable tokens.

| Tab | Disk scope | Meaning |
| --- | --- | --- |
| **Artifacts** | `artifacts/`, `harness/`, `agent/artifacts/` | Harness-published product files (JSON results, terminal, etc.) |
| **Runtime** | root `effects.jsonl`, `cleanup.json`, `summary.json`, `agent.json`, `harness.json` | Attempt bookkeeping — not publishable outputs |
| **Agent** | `agent/` | Invocation trees, trajectory raw, backend_raw |
| **Verifier** | `evaluation/`, `eval_staging/`, `result.json` | Evaluator side |

SPA file preview: JSON/JSONL pretty-print + lightweight syntax highlight (no extra deps).

Job and evidence paths stay inside the dataset chosen by `?dataset=` (or the only opened dataset). `job_id` / `task_id` / `run_id` are single-segment; file paths reject `..`. Package preview roots are only: that dataset directory, an indexed plugin or Agent package under `$AGEVAL_HOME`, or a builtin tree shipped in the CLI. Never `credentials`. Never the whole `$AGEVAL_HOME`. A basename that contains `env` and ends in `.example`, `.sample`, `.template`, or `.dist` previews as text. `.env`, `.env.local`, `.env.production`, and other `.env.*` basenames stay redacted. No Registry required.  
Evidence roots: `{dataset}/.ageval/runs/{run_id}` or task-local `.ageval/runs/`; lock `task_id` must match when present.  
Old `/api/dataset` and `/api/tasks/...` browse routes stay absent.

## Build & serve

```bash
# from apps/viewer — pnpm only (not npm)
pnpm install
pnpm build          # → dist/
# from repo root
uv run ageval view <dataset> --no-browser
```

Python must serve **`apps/viewer/dist/`** (production build). There is **no** separate `static/` source tree.  
Dev: `ageval view --dev` starts the API and tries to spawn Vite. If that cannot run, it prints `pnpm --dir apps/viewer dev`. Same API as production `ageval view`. Deep-link with `--open /jobs/...`.

## Theme

- Modes: **light** | **dark** | **system** (default system).
- Toggle in top-right header; persist `localStorage` key `ageval-viewer-theme`.
- Tokens via `data-theme` + CSS variables in `src/index.css`.

## CLI command strip

- Render with shell-style highlighting (not flat link-blue).
- Dark code surface (`code-bg`); token kinds: cmd / flag / string / path / plain.

## Delivery rules

- Prefer phase commits: design docs → API → scaffold → pages → polish.
- Do not claim #22 Leaderboard done.
- `tests/viewer/` is the Python HTTP API. Keep `uv run pytest tests/viewer/ -q` and `pnpm build` green. Website, Hub, and Viewer UI is checked by a person on the rendered page. Do not add a component, snapshot, or browser test file under `apps/` or `website/`. Do not add a pytest that asserts visible copy, class names, DOM ids, or markup the test itself wrote.
- Column labels map ageval fields for operators, e.g. `Result` ≈ `mean_score` / `pass_rate`, `Trials` ≈ task counts.

## Anti-patterns (reject in review)

- Visual slop: [DESIGN.md](./DESIGN.md) **Taste** (hero / purple / eyebrows / em-dash / search IKB focus)
- Recreating ad-hoc full-page CSS SPA as default
- Ignoring breadcrumb click-through
- Unsortable tables when columns are metric-like
- Shipping unbuilt `src/` only (always produce `dist/` for `ageval view`)
- Native `<select>` for a product list when shadcn `Select` already exists
- Digest / `run_id` as the visible label in a version or filter menu
