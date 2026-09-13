# ageval Viewer

Local results console for a dataset package:

**Jobs → Tasks → Attempt (trial / run_id)**, with search, sortable columns, breadcrumbs, and copyable CLI.

## What you see

| Layer | Content |
| --- | --- |
| **Jobs** | Suite runs under `.ageval/suite-runs/` **and** single-task Attempts under `.ageval/runs/` (Kind column: suite vs single) |
| **Tasks** | Per-task status / score / run refs from suite summary (+ local evidence when present) |
| **Attempt** | One `run_id`: outcome strip, actors table, evidence tabs |

### Attempt detail (highlights)

- **Subtitle**: `task · framework · docker · upstream.url` (omit missing; url is an external link when present)
- **Actors**: Role / Harness / Model / **Time** / **Usage**
  - Time = sum of inv `latency_ms` for that `profile_id`
  - Usage = last inv normalized ACP usage for that profile (tokens / cache hit / cost when reported)
  - Fail-open `-` when the entry did not report usage (e.g. some `pi` / `grok-build` paths)
  - Observational only — trajectory and usage are **not** PASS authority
- **Tabs** (only if files exist): Trajectory · Agent · Verifier · Artifacts · Lock · Runtime
- **Multi-role**: Trajectory steps and Agent tree group by `profile_id` (virtual folders; on-disk layout unchanged)

SPA lives under `src/`; Python serves the built `dist/` only.

## Design

- [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md) — visual constitution
- [`apps/shared/DESIGN.md`](../shared/DESIGN.md) — SPA token YAML
- [DESIGN.md](./DESIGN.md) — Taste, reuse map
- [AGENTS.md](./AGENTS.md) — scope, stack, API

## Develop

`ageval view --dev` starts the API and **tries** to start `pnpm --dir apps/viewer dev` (same API). No pre-built SPA. If the repo / pnpm / `node_modules` is missing, it prints the two-process fallback instead of failing.

```bash
uv run ageval view tests/fixtures/datasets/suite-min --dev --port 8765
```

Manual fallback (only if Vite did not start):

```bash
VITE_VIEWER_API=http://127.0.0.1:8765 pnpm --dir apps/viewer dev
```

Two-process contract: API port (`--port`, default 8765) + UI port (`--ui-port`, default 5173). Open `http://127.0.0.1:5173/` (or the `--open` path).

```bash
# Deep-link a job/task/run after ageval run
uv run ageval view examples/core --open /jobs/<suite_or_run_id>
uv run ageval view examples/core --dev --open /jobs/<id>/tasks/<task>/trials/<run>
```

If the port is already in use, stop the other `ageval view` process or pass `--port <free>` (`--port 0` = ephemeral). The CLI error includes a concrete `http://host:port/` URL.

## Production build (required for `ageval view`)

```bash
cd apps/viewer
pnpm install
pnpm build   # writes dist/
uv run ageval view <dataset>
```

Package manager: **pnpm** only (`packageManager` field; do not use npm/yarn).

Python serves **`apps/viewer/dist/`** only (no separate `static/` tree). `dist/` is gitignored.

## API

| Path | Description |
| --- | --- |
| `GET /api/health` | Liveness |
| `GET /api/jobs` | Suite runs and single-task Attempts in this dataset |
| `GET /api/jobs/{id}` | Job + task rows |
| `GET /api/jobs/{id}/tasks/{task_id}` | Task detail, trials list, copyable `ageval run` |
| `GET /api/jobs/{id}/tasks/{task_id}/trials` | Trials (suite + local evidence) |
| `GET .../trials/{run_id}` | Attempt meta: status, actors (Time/Usage), framework, docker, provenance, `available_tabs` |
| `GET .../trials/{run_id}/tree?scope=` | Evidence file tree (`agent` / `verifier` / `artifacts` / `lock` / `runtime` / …) |
| `GET .../trials/{run_id}/file?path=` | File preview (size-capped; secret-like names redacted) |
| `GET .../trials/{run_id}/trajectory` | Parsed `trajectory.jsonl` steps (observational; steps carry `profile_id` when known) |

All ids are single path segments; file paths reject paths that contain `..`. No Registry required for local browse.
