# ageval documentation website

Bilingual Fumadocs site for **ageval**.

This directory is the **reader-facing documentation site**. It does **not**:

- own mechanism or product design specifications (`docs/` and `ARCHITECTURE.md` are authoritative)
- import production `src/ageval` runtime packages
- replace `apps/viewer` (local Viewer SPA) or `apps/hub` (Registry Hub SPA)

## Authority boundary

| Surface                        | Role                                                               |
| ------------------------------ | ------------------------------------------------------------------ |
| `docs/design/` + `docs/PRD.md` | Mechanism / product design authority                               |
| `ARCHITECTURE.md`              | Module structure authority                                         |
| GitHub Issues                  | Incremental delivery tracking                                      |
| **`website/` (this tree)**     | User-facing guides and reference pages (synced when closing tasks) |
| `apps/*` / `services/*` README | SPA / service development detail                                   |

## Local development

From the monorepo root:

```sh
pnpm --dir website install
pnpm --dir website dev
```

Open `http://localhost:3000/en`. Default locale is English at `/en`; Simplified Chinese is at `/zh-CN`.

| Env | Meaning |
| --- | --- |
| `NEXT_PUBLIC_HUB_URL` | Homepage nav/CTA and docs sidebar link to the Hub SPA. Unset = `http://127.0.0.1:5174`. Empty = hide. |
| `NEXT_PUBLIC_BASE_PATH` | URL prefix for GitHub project Pages (`/ageval`). Unset for a domain root. Build-time. |

## Content layout

- `content/docs/*.mdx` — English (default locale)
- `content/docs/*.zh-CN.mdx` — Simplified Chinese, same slug
- `content/docs/**/meta.json` — English navigation
- `content/docs/**/meta.zh-CN.json` — Chinese navigation

### Information architecture

```text
index
getting-started/   # install, first-run
run/               # single-task, suite, switch-agent, campaign, local-viewer, export-evidence, plugins
author/            # tutorial, package-layout, write-run, write-evaluator, docker-and-visibility, provenance
agents/            # acp-profiles, environments, multi-agent
share/             # registry, hub, hosted
reference/         # cli, config-fields, results-and-pass, examples
contribute/        # architecture, contributing
```

## Design system

[DESIGN.md](DESIGN.md) defines the shared visual language: International Klein Blue + cool ink, shared across landing and docs (`Anton` wordmark on landing; `Geist` / `Noto Sans SC` everywhere else).

## Checks

```sh
python3 scripts/check_public_terms.py
pnpm --dir website lint
pnpm --dir website typecheck
pnpm --dir website build
```

## Static export

`pnpm build` writes static HTML to `out/` (`output: "export"`). Search indexes are baked into `search-index.json` and queried in the browser. `/` redirects to `/en/`; `/zh-CN/` serves the Chinese site.

```sh
pnpm --dir website build
pnpm --dir website start   # http://127.0.0.1:3000
```

## GitHub Pages

Pushing to `main` (paths under `website/` or the workflow file) runs [`.github/workflows/website-pages.yml`](../.github/workflows/website-pages.yml): `pnpm build` with `NEXT_PUBLIC_BASE_PATH=/ageval` and the production Hub URL, then uploads `website/out` to `https://zju-real.github.io/ageval/`.

To preview the Pages build locally:

```sh
NEXT_PUBLIC_BASE_PATH=/ageval NEXT_PUBLIC_HUB_URL=https://ageval.zjureal.com/ pnpm --dir website build
mkdir -p /tmp/ageval-pages && rm -rf /tmp/ageval-pages/ageval && cp -R website/out /tmp/ageval-pages/ageval
python3 -m http.server 3000 --bind 127.0.0.1 --directory /tmp/ageval-pages
```

Open `http://127.0.0.1:3000/ageval/`.
