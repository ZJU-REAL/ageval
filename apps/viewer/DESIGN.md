---
# Shared Hub / Viewer theme constants. Must match docs/design/13-web-ui-tokens.md
# (machine-checked). Hub inherits this listing — do not fork a second palette.
# Do not put page layout here (search height, route chrome, which tab sits where).
colors:
  light:
    canvas: "#F1F3F5"
    canvas-soft: "#E9EBED"
    canvas-soft-2: "#E1E5ED"
    hairline: "#D2D6DF"
    hairline-strong: "#979EB1"
    ink: "#14161F"
    body: "#4A4E5C"
    mute: "#5E6376"
    link: "#1B54E8"
    link-deep: "#001F73"
    link-soft: "#DAE2F6"
    error: "#D40000"
    error-soft: "#F7D4D6"
    warning: "#F5A623"
    warning-soft: "#F4ECDE"
    star: "#E3B341"
    code-bg: "#F1F3F5"
    nav-home: "#2F6E4A"
    nav-datasets: "#187A8C"
    nav-leaderboard: "#7A3D62"
    nav-plugins: "#9A5C16"
    nav-agents: "#5A4AA8"
    nav-models: "#5A6B38"
    nav-inbox: "#B34A3C"
    nav-orgs: "#3E5F7A"
  dark:
    canvas: "#1B1E26"
    canvas-soft: "#20242D"
    canvas-soft-2: "#2B3041"
    hairline: "#343948"
    hairline-strong: "#5C6274"
    ink: "#EEF0F6"
    body: "#9AA0B4"
    mute: "#8A90A4"
    link: "#5B7BFF"
    link-deep: "#8AA0FF"
    link-soft: "#1E2645"
    error: "#FF5C5C"
    error-soft: "#3B1414"
    warning: "#F5A623"
    warning-soft: "#3A2E1D"
    star: "#F5C84C"
    code-bg: "#16181E"
    nav-home: "#6FBF93"
    nav-datasets: "#5EC4D4"
    nav-leaderboard: "#C88AA8"
    nav-plugins: "#D4924A"
    nav-agents: "#A898E8"
    nav-models: "#B4C47A"
    nav-inbox: "#E08A7A"
    nav-orgs: "#8AA8C0"
aliases:
  row-hover: canvas-soft
typography:
  sans: "Geist, Inter, system-ui, -apple-system, PingFang SC, Microsoft YaHei, sans-serif"
  mono: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, monospace"
  display: "Anton (wordmark only)"
type-scale:
  display-md: { fontSize: 24px, fontWeight: 600, lineHeight: 32px, letterSpacing: -0.96px }
  display-sm: { fontSize: 20px, fontWeight: 600, lineHeight: 28px, letterSpacing: -0.6px }
  body-sm: { fontSize: 14px, fontWeight: 400, lineHeight: 20px }
  body-sm-strong: { fontSize: 14px, fontWeight: 500, lineHeight: 20px }
  caption: { fontSize: 12px, fontWeight: 400, lineHeight: 16px }
  code: { fontSize: 13px, fontWeight: 400, lineHeight: 20px, fontFamily: mono }
rounded:
  sm: 8px
  md: 10px
  lg: 14px
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
motion:
  duration: 200ms
  ease-smooth: "cubic-bezier(0.22, 1, 0.36, 1)"
  ease-spring: "cubic-bezier(0.34, 1.56, 0.64, 1)"
  ease-glide: "cubic-bezier(0.65, 0, 0.35, 1)"
  press: 80ms
---

# ageval Viewer design

**Visual constitution:** [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
The YAML above is the **SPA-facing token listing** (Hub inherits it). Hex and stacks must match docs/13; the machine check fails if they drift.

This file does **not** inventory routes or page chrome. Product scope lives in [AGENTS.md](./AGENTS.md).

This SPA is a **local results console** for one opened dataset (no Registry). It is not the Hub catalog and not a marketing site.

Do not invent a second accent palette, a catalog-card Jobs list, or hand-rolled chrome over shadcn.

## Taste

The look is already chosen. Do not run a greenfield identity exercise. Skills like `frontend-design` and `design-taste-frontend` are for landings and portfolios; their hero, bento, GSAP, magnetic-hover, and "take an aesthetic risk" playbooks **do not apply**. What does apply: do not ship LLM defaults, and do not ship shadcn's default skin.

**Read:** Jobs → Tasks → Trial for someone who already ran `ageval view`. Scan, compare, copy a command. Cool-ink product chrome, not a gallery.

| Dial | Value | Meaning |
| --- | --- | --- |
| Variance | 3/10 | Predictable chrome. No asymmetric marketing layout. |
| Motion | 3/10 | CSS hover / focus plus the named exceptions in docs/13. Not cinematic. |
| Density | 8/10 | Cockpit. Hairline tables, tight padding, tabular nums. |

### Locked identity

- Cool paper / cool ink. Not warm cream, not black + neon, not newspaper zero-radius.
- One brand accent: IKB. `error` / `warning` / `star` are functional, not a second brand.
- Geist + Geist Mono. Anton never enters this SPA. No serif.
- Hierarchy is hairline, type, and space. A card is not the default wrapper.

### Type and chrome

- Sentence case. `PageHead` is h1 + optional sub + hairline. No numbered kicker. No `uppercase tracking` eyebrow as section rhythm.
- Sans for readable row text. Mono only for commands, digests, and `tabular-nums`.
- Operator-facing controls and table column labels use **body-sm / `text-sm` (14px)**. Caption is timestamps and mute meta, not column names. Do not invent a third, smaller clickable size.
- One radius scale (8 / 10 / 14). Search is stadium. One pop shadow (`--viewer-shadow-pop`). No second liquid shadow token. No new easing.
- Sliding tabs use `liquid-gooey` Move (`UnderlineTabs` / `PillTabs`). Do not draw an IKB underline.
- Semantic tokens only (`text-ink`, `border-hairline`). No `slate-` / `zinc-` / `gray-` / raw hex in app code.

### Composition

A new control joins the chrome already on the page. It does not start a new band unless the existing band cannot hold it.

- Read the page before drawing. Match density, alignment, and language of the strip you are entering.
- Fill the row you occupy. A toolbar with one occupant and a vacant stretch is unfinished.
- One job, one language. Section switching is underline tabs. A second exclusive choice on that view is a Select, not another tab strip.
- Visible table columns share the row. Leftover width is not dumped into the first column. A column aligns with its neighbors; a right-aligned shrink cell next to a left-aligned one reads as glued.

### Copy

- Name what the operator controls, not the system (`Delete`, not `suite_run_id` in a menu).
- Active, specific, short. The same verb through the whole flow.
- Empty and error say what to do. They do not apologize or decorate.
- Hyphen `-`. Never em-dash `—`. No "Elevate / Seamless / Next-gen / Unleash".

### Interaction

- Full cycle: loading is `ThinkingLogo` + one line; empty is a centered static stack; error uses the `error` token, inline when it is about a field.
- Scan vs edit focus (docs/13). Motion is feedback or state change. Honor `prefers-reduced-motion`.

### Reject

- AI-purple, glow, mesh, glass on chrome, gradient headlines
- Three equal feature cards, bento, div-built fake screenshots
- Decorative status dots, `01 / 02` labels, middle-dot metadata soup
- Skeleton grids, Inter + slate restyle, a second icon family
- A marketing hero inside the console
- Magnetic hover, cursor trail, GSAP, Motion library, scroll hijack

## Reuse first

Before drawing a control:

1. Find the same job already shipped here or in Hub (`src/components/` / `src/components/ui/`).
2. Copy that instance — including focus, radius, and type classes.
3. If the primitive is missing a slot, extend `src/components/ui/` so Hub and Viewer stay aligned. Do not one-off a native `<select>` / `<input>` / `border-b-2` tab.

`Input`'s default `focus-visible:border-link` is the **edit-field** language in docs/13. Jobs search and other scan chrome keep `border-hairline` on focus (same as Hub `CatalogScopeBar`). Do not accept the primitive default for a new search.

## Role → component

| Role | Use |
| --- | --- |
| Page title | `PageHead` |
| Jobs / tasks rows | hairline `Table` |
| Optional table columns | `TableColumnPicker` |
| Jobs search | `Input` + `focus-visible:border-hairline` |
| Kind / source / time filter | `Select` |
| Row / theme overflow | `DropdownMenu` |
| Evidence section switcher | `UnderlineTabs` (Liquid Move) |
| Command | `CommandStrip` (shell highlight on `code-bg`, not flat link-blue) |
| Dialog / confirm | existing confirm / pop (`data-ageval-pop`); portal to body / overlay root |
| Loading / empty | `ThinkingLogo` loading vs centered empty stack (docs/13) |

Viewer has no Hub sidebar. Header is opaque `canvas-soft` + `border-b` and spans the viewport. Main is `canvas`; wide (`xl`) copy is `w-[80%]` centered. Brand is the owl lockup; page-action icons stay `mute`.
