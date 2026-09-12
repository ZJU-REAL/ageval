# ageval documentation website

Bilingual Fumadocs site for **ageval**.

This directory is a **reader-facing product projection**. It does **not**:

- own design or delivery truth
- import production `src/ageval` runtime packages
- replace `apps/viewer` (local suite UI) or `apps/hub` (Registry SPA)

## Authority boundary

| Surface                        | Role                                                               |
| ------------------------------ | ------------------------------------------------------------------ |
| `docs/design/` + `docs/PRD.md` | Mechanism / product design authority                               |
| `ARCHITECTURE.md`              | Module structure authority                                         |
| GitHub Issues                  | Delivery tracking                                                  |
| **`website/` (this tree)**     | How-to and product navigation (rewritten; not a mirror of `docs/`) |
| `apps/*` / `services/*` README | SPA / service **dev** detail                                       |

Conflict → fix `docs/` (or Architecture / Issues) first, then sync this site.

## References (scaffold & IA)

| Purpose                        | Remote                                                                                                       |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Framework, visual system, i18n | [`ZJU-REAL/BORA-v1`](https://github.com/ZJU-REAL/BORA-v1) → `website/`                                       |
| Content module grouping (IA)   | Historical v0 site sections: `index` / `get-started` / `concepts` / `protocols` / `operations` / `developer` |

## Local development

From the monorepo root:

```sh
pnpm --dir website install
pnpm --dir website dev
```

Open `http://localhost:3000/en`. Default locale is English at `/en`; Simplified Chinese at `/zh-CN`.

| Env | Meaning |
| --- | --- |
| `NEXT_PUBLIC_HUB_URL` | Homepage nav/CTA and docs sidebar link to the Hub SPA. Unset = `http://127.0.0.1:5174`. Empty = hide. |
| `NEXT_PUBLIC_BASE_PATH` | URL prefix for GitHub project Pages (`/ageval`). Unset for a domain root. Build-time. |

## Content layout

- `content/docs/*.mdx` — English (default locale)
- `content/docs/*.zh-CN.mdx` — Simplified Chinese, same slug
- `content/docs/**/meta.json` — English navigation
- `content/docs/**/meta.zh-CN.json` — Chinese navigation

### Information architecture (job-oriented)

```text
index
getting-started/   # 入门：install, first-run
run/               # 运行：single-task, suite, switch-agent, campaign, viewer, export
author/            # 编写 Dataset：tutorial, layout, harness, evaluator, docker, provenance
agents/            # Agent 接入：acp-profiles, multi-agent, l1-docker
share/             # 结果共享：registry, hub
reference/         # 参考：cli, config-fields, results, examples
contribute/        # 贡献：architecture, contributing
```

Writing rules: usage-path IA with professional product tone; bilingual zh-CN / en; no whole-page mirror of `docs/design`.

## Design system

[DESIGN.md](DESIGN.md) defines one chrome: Klein Blue + cool ink, shared by landing and docs (Anton wordmark on landing; Geist / Noto Sans SC everywhere else).

## Checks

```sh
pnpm --dir website lint
pnpm --dir website typecheck
pnpm --dir website build
```

## Static export

`pnpm build` writes HTML to `out/` (`output: "export"`). Search indexes are baked into `search-index.json` and queried in the browser. There is no Node server and no locale-detecting middleware: `/` redirects to `/en/`; `/zh-CN/` is the Chinese site. Chinese queries use the default tokenizer (no Mandarin segmenter).

```sh
pnpm --dir website build
pnpm --dir website start   # http://127.0.0.1:3000
```

## GitHub Pages

Push to `main` (paths under `website/` or the workflow file) runs [`.github/workflows/website-pages.yml`](../.github/workflows/website-pages.yml): `pnpm build` with `NEXT_PUBLIC_BASE_PATH=/ageval` and the production Hub URL, then uploads `website/out`. The site is `https://zju-real.github.io/ageval/`.

Repo Settings → Pages → Source must be **GitHub Actions**.

To preview the Pages-shaped build locally (links are under `/ageval/`):

```sh
NEXT_PUBLIC_BASE_PATH=/ageval NEXT_PUBLIC_HUB_URL=https://ageval.zjureal.com/ pnpm --dir website build
mkdir -p /tmp/ageval-pages && rm -rf /tmp/ageval-pages/ageval && cp -R website/out /tmp/ageval-pages/ageval
python3 -m http.server 3000 --bind 127.0.0.1 --directory /tmp/ageval-pages
```

Open http://127.0.0.1:3000/ageval/ .

## Not in scope here

- Hub / Viewer feature work (those live under `apps/`)
