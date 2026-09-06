# ageval Hub design

**Visual constitution:** [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
**SPA token listing:** YAML frontmatter in [`apps/viewer/DESIGN.md`](../viewer/DESIGN.md) (shared Hub/Viewer constants; machine-checked against docs/13). Do not fork a second palette here.
**Hub product** (Registry, listing, Performance, `?model=`): [`docs/design/12-hub-dataset-and-leaderboard.md`](../../docs/design/12-hub-dataset-and-leaderboard.md), [`docs/design/14-agent-hub.md`](../../docs/design/14-agent-hub.md).

This file does **not** inventory routes, tabs, or where a control sits on a page. It tells implementers which shipped component to reuse so a new control matches the product, not the shadcn default.

This SPA is the **Registry catalog**. It is not `apps/viewer` / `ageval view`.

Do not invent a second marketing skin or hand-rolled full-page CSS over shadcn.

## Taste

The look is already chosen. Shared anti-slop (copy, type, reject list, landing-playbook ban) is in [`apps/viewer/DESIGN.md`](../viewer/DESIGN.md) **Taste**. This section only adds Hub dials and catalog rules.

**Read:** Registry catalog for benchmark authors. Browse packages, open a dataset, scan a leaderboard. Same cool-ink chrome as Viewer, slightly less dense.

| Dial | Value | Meaning |
| --- | --- | --- |
| Variance | 3/10 | Predictable chrome. Sidebar + main column, not a marketing grid. |
| Motion | 3/10 | CSS hover / focus plus liquid-gooey Move and the other named exceptions in docs/13. Not cinematic. |
| Density | 6/10 | Catalog cards where identity matters; hairline tables where rows compare. |

### Hub chrome

- Left/right shell: entire aside opaque `canvas-soft` + `border-r`; header and main `canvas`. Logo row `border-b`; GitHub / Documentation footer `border-t`. No glass, no blur wash. Wide (`xl`) main copy is `w-[80%]` centered; the top bar still spans the main column.
- Selected sidebar row is Liquid Move fill `canvas`. Hover is `canvas/50`. Do not reuse `canvas-soft-2` on the rail — it disappears against the soft aside.
- `nav-*` paints lucide only. Labels stay `ink` / `body`, sans, body-sm. Do not flood the page with those colors.
- Marketplace entities (plugin / agent) are `CatalogCard` (squish press, three-line description, three columns at `xl`). Comparable rows (datasets, jobs, leaderboard, members) are tables. Do not put a dataset in a card "to match plugins". Model encyclopedia is a lab-grouped directory, not a third marketplace: dense rows under a lab header, never `CatalogCard`, never wrapping `Chip`. Harness Model region reuses `ModelItem` as a flat list — no lab grouping.
- Star on a card is a count. The write control is on the package, not the list cell.
- Search on a catalog list copies `CatalogScopeBar`.
- Layout: Viewer DESIGN.md **Composition**. New chrome joins the band already scanning the page. Density 6/10 is not an excuse for a vacant half-row.

### DashButton (fill-in slot)

Hairline **dashed underline**, not a boxed button. Used for Attach role / agent / model.

Motion is the same CSS budget as the rest of Hub (`200ms` / `--ease-smooth`). Do not unmount the hover list on leave (that kills the exit). Do not add GSAP / Motion.

| State | What happens |
| --- | --- |
| Rest | Underline `border-hairline` dashed |
| Hover / open | Underline → `border-mute`, **200ms ease-smooth** |
| Hover list in | List stays mounted. Reveals **downward** (`grid-template-rows` `0fr` → `1fr`) and fades `opacity` 0 → 1, same **200ms ease-smooth**, origin top. Cap `max-h-56` then scroll |
| Hover list out | Reverse of the same curve. Pointer leaves the slot **or** the list |
| Click the slot | Opens the search palette (agent / model). Role has no palette; pick from the list |
| `prefers-reduced-motion: reduce` | Skip duration; jump to the open / closed state |

## Reuse first

Before drawing a control:

1. Find the same job already shipped (`src/components/` or `src/components/ui/`).
2. Copy that instance — including the classes that encode focus, radius, and type.
3. If nothing exists, add a primitive under `src/components/ui/` (share with Viewer when the control is chrome). Do not one-off a native `<input>` / `<select>` / `border-b-2` tab.

`Input`'s default `focus-visible:border-link` is the **edit-field** language in docs/13. Search, filter, and other scan chrome keep `border-hairline` on focus. Copy `CatalogScopeBar`, not the primitive default.

Token values, type stacks, radii, and motion curves: the YAML in Viewer `DESIGN.md`. Focus roles and catalog-vs-table: docs/13.

## Role → component

| Role | Use |
| --- | --- |
| Page title | `PageHead` |
| Section switcher | `UnderlineTabs` (Liquid Move) |
| In-page exclusive choice | `Select` |
| Compact in-panel segment | `PillTabs` |
| Wrapping label | `Chip` (overlay paths, plugin names in a preview — **not** model browse) |
| Fill-in slot (Attach role / agent / model) | `DashButton` (hairline dashed underline → mute on hover, 200ms ease-smooth; hover list expands downward 0fr→1fr + fade; click opens the search palette) |
| Marketplace plugin / agent | `CatalogCard` / `CatalogCardGrid` |
| Model encyclopedia detail | `/models/{canonical}`: identity then `UnderlineTabs` Overview / Performance. Overview is a BindingPreview-style `blob-panel` spec list. HF mark + link only when the pin has a Hugging Face URL. No per-gateway price table. Performance `blob-panel` + `Table`. Not `CatalogCard`. |
| Model encyclopedia | `/models` plaza: one `blob-panel` + `Table` **per lab** (shared `colgroup` + `table-fixed` so columns align; `Table` wrap is `overflow-visible` so sticky is still `#main`). Lab title is a row above the panel (`LabGroupHead`, `text-base`) with mark + official link + `lab-info` blurb. Model cell: name links `/models/{canonical}` with modality badges, canonical id below in mute. Columns: Model / Released / Context / Output / Price per MTok. `SortableHead` shared across labs. `#main` is the only scroller. Toolbar is `sticky top-0` (`-mt-5 pt-0`, opaque `bg-canvas` plus an upward canvas cap) so it sits flush under the shell header at rest and when stuck, covering `#main`’s `pt-5` gap; `--models-stick-top` is the toolbar’s visible bottom vs `#main`; lab head / `th` stick flush under that. Not `CatalogCard`. Not wrapping `Chip`. Lab ≠ Hub `org_id`. Scope is `CatalogScopeBar variant="select"` (Explore All / With Performance); modality `UnderlineTabs` follow. Liquid fill stays `canvas-soft-2`; selected/hover tints the icon only. Param counts are not in the pin; do not fake them. |
| Harness model directory | `/agents/{id}` Model region: flat `ModelItem` list (same row as the search palette, including lab mark). One column, two at `lg`. Height caps at three rows (`--model-row: 4rem` plus `gap-2`), then the list scrolls. Each item has a hairline border. Chips are context + price only (`meta="compact"`); released stays on the search palette. No lab/provider grouping. Default badge on the package default. Click sets `?model=` on this page. |
| Catalog list (scope + search) | `CatalogScopeBar` (`/models` Explore All = full pin; With Performance = has Performance) |
| Model row | `ModelItem` (lab mark + name + modality badges + canonical/overlay; context / price chips, plus released when `meta="full"`). Search palette and harness Model region share this; plaza tables do not. |
| Model search palette | `ModelSearchModal` (Cmd/Ctrl+F on `/models`; glass dialog of `ModelItem` rows over the pin — lab mark on; models only, no providers; Enter opens `/models/{canonical}`) |
| Comparable rows (datasets, jobs, leaderboard, members, model Performance) | hairline `Table` inside `blob-panel` |
| Sortable table column | `SortableHead` (click cycles asc → desc → default) |
| Score in a comparable row | `ScoreRing` (IKB arc + number; fill is value/max, default max 1) |
| Optional table columns | `TableColumnPicker` |
| Version list | `VersionSwitcher` (`Select` + human label + trailing date) |
| Filter / overflow menu | `Select` / `DropdownMenu` |
| Persistable name / description | `FloatingField` / `DisplayNameEditor` / `DescriptionEditor` |
| Command | `CommandStrip` |
| Copyable file fence | `CodeFence` (Shiki from path, hairline + code-bg; not the lightweight tokenizer) |
| Dialog / confirm | `FrameModal` / `ConfirmDialog` (portal via `OverlayRoot` / `document.body`) |
| Loading / empty | `ThinkingLogo` loading vs centered empty stack (docs/13) |

New chrome that both Hub and Viewer need starts as a `src/components/ui/` primitive, used on both sides.
