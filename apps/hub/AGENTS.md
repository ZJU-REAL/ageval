# apps/hub — agent scope lock

Visual language: [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
Theme constants: YAML in [`apps/shared/DESIGN.md`](../shared/DESIGN.md) (shared).
Which component to reuse: [DESIGN.md](./DESIGN.md). This file is product scope.

| Do | Do not |
| --- | --- |
| Browse Registry packages (Datasets) | Replace local `ageval view` Jobs IA |
| README + Files (package tree via #38) | Full Run/Attempt evidence browser (#43) |
| Task Jobs **list only** | Click-through into trial trajectory |
| Leaderboard tab (#40) | Suite-level PASS authority |
| Agent Performance on `/agents/:id` — derived plaza / consented `agent_ref`; `?model=` is overlay invoke id on a model directory (not Chip). `/models` is the pin encyclopedia | Persist a Runtime table; invent suite or per-role PASS; keep `/runtimes`; add `/agents/:id/models/:model` or `package_kind=model` |
| Same stack as viewer (Vite/React/shadcn) | Second component library / marketing CSS |

Registry API is the data plane. Token stays in browser storage only.

Do not describe page layout in this file. Hub product rules stay in docs/12 and docs/14.
Taste: [DESIGN.md](./DESIGN.md) plus Viewer DESIGN.md **Taste**. Not a landing.

## UI reuse (mandatory)

Stack is Vite + React + Tailwind + **shadcn/ui**. Overlap primitives live in
`apps/shared/components/ui/`; Hub-only controls stay under `src/components/ui/`
(chip, dash-button). Same family as Viewer. Role → component map: [DESIGN.md](./DESIGN.md).

1. **Reuse a shipped control.** Copy an existing instance, including its
   focus classes. Version / filter / menu lists use
   `@ageval/shared/components/ui/select` (see `VersionSwitcher`) or
   `@ageval/shared/components/ui/dropdown-menu`. Catalog search uses `CatalogScopeBar`.
2. **No native chrome.** Product UI must not use raw `<select>`, `<option>`,
   or unstyled `<button>` as the visible control. Radix/shadcn owns focus,
   trigger, and list.
3. **Do not trust primitive defaults.** `Input` defaults to edit-field IKB
   focus (`border-link`). Scan chrome (search / filter / `Select` trigger)
   keeps `hairline` on focus — docs/13. A new search that "uses Input" and
   keeps the default is wrong.
4. **Operator labels, not digests.** Dropdown rows show a human label
   (`versionLabel`, `patch N`) plus a date via `SelectItem` `trailing` /
   `formatDay` / `formatDate`. `run_id`, sha256, and other identity strings
   stay in the breadcrumb / mono heading, not in the list text.
5. **Catalog cards for plugins and agents.** Marketplace packages use
   `CatalogCard` / `CatalogCardGrid`. Datasets are org-grouped hairline
   tables (`DatasetOrgTables`); jobs, leaderboard, members, suites, and
   model Performance stay flat hairline tables. Model encyclopedia
   is lab-grouped tables (`ModelLabTables`). Harness Model region is a flat `ModelItem` list
   (no lab/provider grouping) — not cards, not wrapping `Chip`.
6. **One language per job.** Section switchers use `UnderlineTabs`.
   Compact in-panel segments use `PillTabs`. A second exclusive choice
   on the same view uses `Select`. Do not stack two tab strips or
   hand-roll `border-b-2`.
7. **Compose, then draw.** New chrome joins the toolbar already on
   the page. Do not open a vacant band for a single control. Operator
   labels use body-sm. How a primitive is drawn: [DESIGN.md](./DESIGN.md)
   plus Viewer Taste **Composition**.

New overlap chrome requires a new `apps/shared/components/ui/` primitive first, used by both
Hub and Viewer. Do not one-off style a native element.

## Checks

Website, Hub, and Viewer UI is checked by a person on the rendered page. Do not add a component, snapshot, or browser test file under `apps/` or `website/`. Do not add a pytest that asserts visible copy, class names, DOM ids, or markup the test itself wrote. Hub CI stays `pnpm lint` and `pnpm build`.
