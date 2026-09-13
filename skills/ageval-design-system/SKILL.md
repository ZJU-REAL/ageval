---
name: ageval-design-system
description: >
  ageval web UI style rules for coding agents editing website (landing + docs),
  apps/hub, or apps/viewer: canonical color tokens (cool paper/ink + IKB
  #1B54E8/#5B7BFF), font stacks (Geist/Anton wordmark-only), radius,
  role-based focus (scan chrome keeps hairline; edit fields use IKB border),
  reuse of shipped components, the ten invariants, and the machine check
  scripts/check_design_tokens.py. Use when adding or restyling UI in any of the
  three web surfaces, picking colors or fonts, adding icons, or when a change
  touches raw hex, focus rings, buttons, search fields, or the owl brand assets.
  Authority is docs/design/13-web-ui-tokens.md; apps/shared/DESIGN.md YAML is
  the SPA token listing (Hub/Viewer inherit it); SPA DESIGN.md Taste is anti-slop
  (product chrome, not landing) plus the reuse map.
  This skill only routes and summarizes — it is not a page inventory.
---

# ageval web UI design system

Three surfaces, one language: website landing, website docs (fumadocs),
hub SPA, viewer SPA. Authority: `docs/design/13-web-ui-tokens.md`
(constitution: tokens, focus roles, motion — **not** a page inventory).

On Hub / Viewer, also read `apps/shared/DESIGN.md` YAML (shared theme constants),
that SPA's `DESIGN.md` **Taste** (anti-slop) and role table, and `AGENTS.md`
(scope). Copy a shipped instance. Do not restyle a shadcn primitive default
and call it on-brand.

Hub and Viewer are **product consoles**. Do not apply landing/portfolio
playbooks (`frontend-design`, `design-taste-frontend` hero / bento / GSAP /
magnetic / "invent a new identity"). Identity is already locked: cool paper
+ IKB + Geist. Spend the skill budget on not looking like default shadcn.

## Where tokens live

| Surface      | Token file                                                              |
| ------------ | ----------------------------------------------------------------------- |
| constitution | `docs/design/13-web-ui-tokens.md`                                       |
| SPA listing  | `apps/shared/DESIGN.md` YAML (Hub/Viewer inherit; do not fork)          |
| hub / viewer | `apps/shared/css/tokens.css` (`--viewer-*` + `@theme`; each `index.css` `@import`s it) |
| docs         | `website/src/app/global.css` (`--color-fd-*`, `--ageval-link*`)           |
| landing      | Token block at the top of `website/src/components/landing/landing.css`  |

Change order: edit the table in `docs/design/13` first → sync script `CANONICAL`
→ sync `apps/shared/DESIGN.md` YAML and `apps/shared/css/tokens.css` → run the machine check.
If they disagree, fix the copies to match docs/13 + the script.

## Quick rules (full list in docs/design/13)

- Hex values live only in token files and owl brand assets. App code uses semantic
  names (`text-ink`, `border-hairline`, …).
- IKB (`link` / `primary`) is for links, focus, primary CTAs, and brand slots.
  Do not use it as a large fill. Functional accents (error, warning, star gold)
  have their own tokens; the UI is not ink/paper/IKB-only.
- `mute` is never body text. `canvas*` is surface, `hairline` is line,
  `ink` / `body` / `mute` are type.
- Anton is wordmark-only. Body is Geist (+ CJK fallback). Mono is Geist Mono.
- Radii are 8 / 10 / 14px only. Primary CTA (SPA Button `default`) is IKB fill +
  `rounded-[8px]` + mono 13px + pop shadow + `focus-visible:ring-2 ring-link/70`.
  Search is stadium. Do not use clip-path chamfer on buttons.
- Section tabs use `UnderlineTabs` (sans `text-sm`, liquid-gooey Move thumb, fill
  `canvas-soft-2`). Do not draw an IKB underline. Page heads use `PageHead`
  (h1 + optional sub + hairline; no numbered kicker). One tab strip per view; a
  second exclusive choice is `Select`. Wrapping chips use `Chip`, not `bg-link/10`.
- Operator-facing controls and table column labels use body-sm 14px. Caption is
  timestamps and mute meta, not column names. Do not invent a smaller clickable size. A button group is one hairline box; selected fill
  is `canvas-soft-2`. New chrome joins the toolbar already on the page — do not open a
  vacant band for a single control. Layout: SPA DESIGN.md **Composition**.
- List / table row text (non-numeric): always default sans. Mono only for
  `<code>` / `<pre>` / command strips, and numeric `tabular-nums` alignment.
- Plugin / agent marketplace lists are `CatalogCard` grids. Datasets are
  org-grouped hairline tables; jobs, leaderboard, and members are flat
  hairline tables. Do not put slot/binding tags
  on cards.
- Motion is CSS only on hub/viewer, plus two named exceptions in docs/13:
  `ThinkingLogo` canvas and `liquid-gooey` Move (tabs / Hub sidebar). Default
  `200ms` / `ease-smooth`. Also `--ease-spring` (toast, star burst, squish
  release), `--ease-glide` (thumb CSS), `--t-press` 80ms. Morph does not ship.
  Website docs/landing do not take the library. Landing may stagger the hero and
  reveal sections 8px; no GSAP/Motion, pin/scrub, magnetic hover, or cursor trail.
- Focus is role-based (docs/13), not "every field goes IKB":
  buttons / links / cards `ring-2 ring-link/70`; **edit** fields 1px
  `border-link`; **scan** chrome (search, filter, Select trigger) keeps
  `border-hairline` — no border color change. Landing 3px outline.
  Hub search copies `CatalogScopeBar`, not `Input`'s default.
- Popover / card shadow is `--viewer-shadow-pop` only (tight pop; no
  `--viewer-shadow-liquid`). Phase charts use `--viewer-phase-1..6` only.
  Hub shell is left/right (`canvas-soft` aside, `canvas` main). Viewer header is
  `canvas-soft`; docs sidebar matches the aside.
- Icons: product brand uses owl; function icons use lucide; plugin/agent entity
  marks default to the uploader GitHub avatar, or a closed color catalog /
  GitHub login override. Do not add a third-party logo component library as a
  runtime dependency. Catalog hex lives only in `brand-marks/assets/`.
- SPA anti-slop lives in that SPA's `DESIGN.md` **Taste**. Do not copy it here.

## Machine check

```bash
python3 scripts/check_design_tokens.py
```

Checks: docs/13 table ↔ script `CANONICAL` ↔ `apps/shared/DESIGN.md` YAML; mapped
variables stay inside the canonical set; no raw hex in app code (outside the
allowlist).
CI job `design-tokens` runs the same command. Run it locally after token or
style edits.
