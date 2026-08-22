# ageval Hub design

**Visual authority:** inherits [`apps/viewer/DESIGN.md`](../viewer/DESIGN.md)
(Klein Blue / cool-ink product chrome, hairline tables, tabular nums).
Token and invariant authority: [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).

This SPA is **Registry catalog** (Datasets → Task files / Jobs list / Leaderboard),
**not** the local Jobs → Trial evidence browser (`ageval view`).

Do not invent a second marketing skin or hand-rolled full-page CSS over shadcn.

## Catalog vs table

| Surface | UI | Why |
| --- | --- | --- |
| Plugins (`/plugins`, Home, org, user public) | **Catalog cards** (`CatalogCard` / `CatalogCardGrid`) | Marketplace identity: `org/name` + official, **or** builtin short id + lucide builtin mark (Explore only; no org) |
| Agents (`/agents`, Home, org, user public) | **Catalog cards** | Same: one job binding is a package |
| Datasets, jobs, leaderboard, members, suites | **Hairline tables** | Dense comparable rows (sort, scan, bulk) |

### Catalog card rules

- Radius 12px, hairline border, `canvas` fill. Hover: `canvas-soft`. Focus: `ring-2 ring-link/70`.
- Motion: default `200ms` / `ease-smooth`. PillTabs / toast / star burst / squish use the named exceptions in docs/design/13.
- Grid: `1 / 2 / 3` columns (`grid-cols-1 sm:grid-cols-2 xl:grid-cols-3`). N packages → N cells.
- Header: published packages use `org/name` plus official mark on the left, updated date on the right. Builtin contrib rows use the short id (no `org/` prefix) plus a lucide builtin mark — not `OfficialMark` / `BadgeCheck`, and not the “Verified official plugin” tooltip. Omit the date unless a real timestamp exists (builtin catalog rows have none).
- Description: fixed two-line block (`h-10` / `leading-5` / `line-clamp-2`). Missing description uses `ageval.plugin/1 package` / `ageval.agent/1 package`. List rows without preview load by-digest meta. Builtin rows **must** ship `plugin_preview` on the list payload; there is no blob to fetch.
- Builtin plugin detail (`/plugins/<short-id>`): description + declared slots from the catalog. Hide install `CommandStrip`, files panel, visibility/delete. Recognition on Hub is not “this host can run”.
- Leaderboard / suite plugin chips: builtin short ids (`acp`, `openai-http`, environments) stay on the row and link to `/plugins/<id>`. Distinguish them from `org/name` marketplace packages. Do not drop them via a client-side builtin-executor denylist.
- Tags sit at the bottom of the card (`mt-auto`). Mute counts (`download_count` + star count) share that same row on the right (lucide `Download` / `Star` + number). The star on a card is a count, not a control. Builtin overlay rows have no blob, so omit those counts and do not star them.
- Builtin overlay rows appear on **Explore** `/plugins` only. They must not appear in Your organizations / mine, org detail, Home, or user public lists (no uploader, no org).
- Loading uses `CatalogCardSkeleton` (same grid, pulse). Empty states use a dashed well.

## Motion

- Default duration `200ms`, easing `ease-smooth` (`cubic-bezier(0.22, 1, 0.36, 1)`). Close/dismiss can be faster than open; tooltip wait is `80ms` (intent delay, not a travel duration).
- Named exceptions (docs/design/13): `--ease-spring` (toast enter, star burst, button release), `--ease-glide` (PillTabs indicator, 250ms), `--t-press` 80ms on `:active`.
- Underline tabs (`UnderlineTabs`) slide the IKB bar with `transform` + `width`. File-tree Local / Shared / Overlays use `PillTabs` (gliding pill). Do not reintroduce per-page `border-b-2` tab copies or hard-cut segmented fills.
- Toast (`Toaster` + `toast()`) after key writes that have no local success state (save description/name, visibility, delete). Copy and star stay on the control. Overshoot from below; reduced-motion shows the card with no travel.
- Select / dropdown lists enter with `data-ageval-menu`. Modal/tooltip enter with `data-ageval-pop` / `data-ageval-scrim`. Honor `prefers-reduced-motion`.
- No GSAP or Motion on Hub. No magnetic hover, cursor trail, 3D tilt, or scroll hijack.
