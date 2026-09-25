# ageval Viewer design

**Visual constitution:** [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
**SPA token listing:** YAML frontmatter in [`apps/shared/DESIGN.md`](../shared/DESIGN.md) (Hub and Viewer share it; machine-checked against docs/13). Do not fork a second palette here.

This file does **not** inventory routes or page chrome. Product scope lives in [AGENTS.md](./AGENTS.md).

This SPA is a **local results console** for datasets, plugins, and Agent packages on this machine (no Registry write). It is not the Hub catalog and not a marketing site.

One dataset root and a directory of dataset roots share the same header: Datasets, Jobs, Agents, Plugins. No sidebar. On Jobs, the dataset is a Select, not a second tab strip. List search and filters stay pinned. Dataset tables group by the organization in `dataset_id`. Package files are a read-only tree (README first), not a catalog card. Plugin detail reuses the Hub slot timeline.

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
- Operator-facing controls and table column labels use **body-sm / `text-sm` (14px)**. Caption is timestamps and mute meta, not column names. Do not invent a third, smaller clickable size. On the trial page, the outcome values and the Tokens / Timing totals use `figure` (16px). Tables, checks, and step elapsed times do not.
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

1. Find the same job already shipped in `apps/shared` or this SPA.
2. Copy that instance — including focus, radius, and type classes.
3. If the primitive is missing a slot, extend `apps/shared/components/ui/` so Hub and Viewer stay aligned. Do not one-off a native `<select>` / `<input>` / `border-b-2` tab.

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
| Verifier dual surface | hairline button group on the same tab row (copy `CatalogScopeBar` `variant="group"`), far right; Trajectory / Files, trajectory first |
| Trajectory step filter | Trajectory tab row, far right. `Select` (copy `BoardChartControls`). Default All. One major present in the trace (User, Agent, Thought, Tools, Observation, Terminal, Permission, Message). Trigger and menu reuse that major's step icon and tone. Hidden when fewer than two majors are present. |
| Trajectory step outline | Right of the trajectory port (`lg+`, `xl` gutter). Collapsed hairline bars, length by preview. Hover expands the step icon and one truncated line. Click scrolls that step to the top of the port. Hidden below two steps. |
| Command | `CommandStrip` (shell highlight on `code-bg`, not flat link-blue) |
| Dialog / confirm | existing confirm / pop (`data-ageval-pop`); portal to body / overlay root |
| Loading / empty | `ThinkingLogo` loading vs centered empty stack (docs/13) |

Viewer has no Hub sidebar. Header is opaque `canvas-soft` + `border-b` and spans the viewport. Main is `canvas`; wide (`xl`) copy is `w-[80%]` centered. Brand is the owl lockup; page-action icons stay `mute`.
