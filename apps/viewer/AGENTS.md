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

**In scope (MVP):**

1. **Jobs list** — search; filter dropdowns; sortable columns; row click  
   Jobs = suite runs under `.ageval/suite-runs/` and single-task Attempts under `.ageval/runs/`
2. **Job → tasks** — task table with scores / status / agent-model meta
3. **Task detail** — trials/run row(s), status/error coloring, **copyable CLI**
4. **Attempt / trial detail** — `Jobs > job > task > run_id`; Outcome + actors
   (Role / Harness / Model / Time / Usage) + tabs from real evidence only
   (Trajectory · Agent · Verifier · Artifacts · Lock · Runtime). Top bar may show
   framework / environment kind / `provenance.upstream.url`. Multi-role groups Trajectory
   and Agent tree by `profile_id`. Usage/trajectory are observational ≠ PASS.
5. **Breadcrumb** — `Jobs > jobId > taskId > runId` with `>` separators; click to navigate
6. **Delete a local Job** — Jobs row menu or bulk selection. Preview paths /
   bytes / cascade `run_id`s, then confirm. Suite delete always removes
   referenced Attempts. No delete control on an inner trial. Does not call
   Registry. Same Application use case as `ageval jobs delete --local … --yes`.
7. **Pin / note (this browser)** — `localStorage` keyed by `dataset_id` +
   `job_id`. Not written to evidence, lock, or Registry. Pinned rows sort
   first. Action icon (always on): note, else pin, else hover settings.
   Hover a note icon to read the note.
   Click the settings/note control to open the menu (do not open on hover).

**Out of scope unless user asks:**

- Public catalog, OAuth, Postgres, Leaderboard SPA (#22)
- Hub / Registry write (publish, upload, release, remote delete)
- Package file-tree / task-package browser (removed; Jobs is the product surface)
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
| `GET /api/jobs` | Job list (suite-runs + single-task Attempts) |
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

Package-file browse routes were removed with the old SPA.  
All paths confined to the opened dataset root (`job_id` / `task_id` / `run_id` single-segment; file paths reject paths that contain `..`). No Registry required.  
Evidence roots: `{dataset}/.ageval/runs/{run_id}` or task-local `.ageval/runs/`; lock `task_id` must match when present.

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
