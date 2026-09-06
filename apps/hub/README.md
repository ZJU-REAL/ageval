# ageval Hub (`apps/hub`)

Registry **Dataset catalog** SPA: list packages, open README and tasks, preview
files, browse Task Jobs, and Leaderboard.

Also covers the **Plugin marketplace** (`/plugins` — `ageval.plugin/1` browse +
CLI install copy; no browser-side install), **Agents** (`/agents` —
published `ageval.agent/1` harness packages plus derived Performance from
official public Leaderboards that carry `agent_ref`; `?model=` focuses a
registered model on the package page; not a stored Runtime and not suite PASS),
**organizations** (members, org
datasets and plugins, shared suite results, invite keys, member add / role /
transfer, leave / dissolve), **GitHub
browser login**, and opening a Job’s run detail when the corresponding Attempt
artifacts were uploaded.

**Not** the local results viewer (`apps/viewer` / `ageval view`).

## Stack

Vite + React + TypeScript · Tailwind + shadcn/ui · pnpm only  
Visual tokens: [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
SPA constants listing: YAML in [`apps/viewer/DESIGN.md`](../viewer/DESIGN.md).
Reuse map: [DESIGN.md](./DESIGN.md).

## Dev

```bash
# Terminal A — Registry (OAuth + org APIs; see services/registry/README.md)
export VITE_REGISTRY_PROXY_TARGET=http://127.0.0.1:8700
uv run --extra registry python -m services.registry.app --host 127.0.0.1 --port 8700

# Terminal B
cd apps/hub
pnpm install
pnpm dev   # http://127.0.0.1:5174  — proxies /v1 → registry
```

Production-shaped stack (Postgres, object store, Registry, Hub) is
`docker compose -f services/registry/docker-compose.yml up -d --build`.
Hub is `http://127.0.0.1:8080` with same-origin `/v1`. Released tags push
`ghcr.io/zju-real/ageval-hub` and `ageval-registry`. Leave `VITE_REGISTRY_URL`
empty in the image.

| Env | Meaning |
| --- | --- |
| `VITE_REGISTRY_URL` | Absolute Registry origin (production SPA). Empty = same origin (dev proxy). |
| `VITE_REGISTRY_PROXY_TARGET` | Dev proxy target (default `http://127.0.0.1:8080` — use **8700** for local Registry). |
| `VITE_GITHUB_URL` | Sidebar GitHub link. Unset = `https://github.com/ZJU-REAL/ageval`. Empty = hide. |
| `VITE_DOCS_URL` | Sidebar documentation link. Unset = `http://localhost:3000/zh-CN`. Empty = hide. |

### Login (browser OAuth)

Hub uses **Authorization Code**, not Device Flow. GitHub OAuth App callbacks:

- `http://127.0.0.1:5174/login/callback`
- `http://localhost:5174/login/callback` (if you use that host)

**Sign in with GitHub** → authorize → `/login/callback` → Registry token in
`localStorage` (header shows avatar / display name when available).

CLI stays on Device Flow: `ageval login` (see `services/registry/README.md`).

### Invite keys

Org **owners** create keys under Settings. The full key is shown **once** in a
modal; the list only shows a prefix. Members join from **Organizations → Join**.

## Routes

| Path | Page |
| --- | --- |
| `/home` | Personal home (uploaded jobs, orgs, maintainable datasets/tasks, uploaded plugins) |
| `/datasets` | Dataset list (**Explore** / **Your organizations**, Explore default + search on one row) |
| `/datasets/:id` | README (loads first) · Tasks (paginated) · Shared · Overlays (when declared) · Leaderboard. Org owner: visibility / delete version / release draft |
| `/datasets/:id?tab=leaderboard&demo=1` | Leaderboard with mock pass@k rows (local smoke only) |
| `/datasets/:id/tasks/:task` | README · Files (Local \| Shared \| Overlays) · Jobs (row opens detail when uploaded) |
| `/plugins` | **Plugin marketplace** list (`package_kind=plugin`) |
| `/plugins/:id` | Plugin detail (exclusive/chain timeline · files · CLI install) |
| `/agents` | Published Agent catalog |
| `/agents/:id` | Agent detail: `?model=` chips + CLI; tabs Overview / Performance / Files |
| `/datasets/:id/suites/:suiteRunId` | Suite run detail (Profiles / Plugin / Jobs / Share). Leaderboard `?suite=` redirects here |
| `/datasets/:id?tab=leaderboard&dataset_version=` | Leaderboard filtered to that Dataset version (omit = all versions) |
| `/organizations` | Your orgs · Create · Join |
| `/organizations/:orgId` | Overview (members · datasets · plugins · agents) · Settings |
| `/users/:login` | Public user profile (official orgs only; signed-out OK) |
| `/datasets/:id/tasks/:task/attempts/:runId` | Remote Attempt detail (Timing / Tokens when present, tabs + trajectory) |
| `/login` | Starts browser OAuth |
| `/login/callback` | OAuth redirect target |

`:id` is URL-encoded `dataset_id` (`encodeURIComponent`).

### Leaderboard metrics (#60)

- Click column headers to sort; default **Pass rate** → **Mean score** →
  `created_at` (not suite PASS).
- When any row has `metrics.pass_at_k` / `n_attempts`, columns **n_attempts**,
  **pass@k**, **pass^k** appear; missing values show `—`.
- Display k = largest entry in `metrics.k_values` (else `n_attempts`). Labels
  show `@k` / `^k`. These are observational; k-attempt is **not** job identity.
- Columns: Agent, Model, metrics, Tasks, **Uploader** (`uploaded_by`), Suite run
  (compact id). Long Agent/Model truncate with full text in `title`.
- Mock rows: `src/lib/leaderboard-fixtures.ts` via `?tab=leaderboard&demo=1`.

## Related

Epic #22 (catalog) · #38–#40 (files / browse / leaderboard) · #51–#55 (org/share) ·
#43 (optional full Attempt upload for remote Job detail) · #60 (pass@k on Leaderboard)
