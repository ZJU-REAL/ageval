# 09 — Web UI Design System Tokens and Component Invariants

This specification is the visual constitution for all three **ageval** web surfaces: `website/` (landing + Fumadocs documentation), `apps/hub/` (Hub SPA), and `apps/viewer/` (Viewer SPA).

**Authority and machine verification**:
- Authority order: **this document** → surface token stylesheets (`apps/shared/css/tokens.css`, `website/src/app/global.css`, `website/src/components/landing/landing.css`) → application components (which reference semantic token names only, never raw hex literals).
- Machine check: `python3 scripts/check_design_tokens.py` (CI job `design-tokens`) cross-verifies the **Color Tokens** table below against `CANONICAL` in the script, the YAML frontmatter in `apps/shared/DESIGN.md`, and CSS variables across all three apps.

---

## Color Tokens

The brand accent is dual-tone **International Klein Blue (IKB)** paired with cool paper/ink neutrals and dedicated semantic tokens for status (`error`, `warning`, `star`) and Hub navigation glyphs (`nav-*`). All hex comparisons are case-insensitive; application code must reference semantic token names only.

| Token | Light | Dark | Purpose | Hub / Viewer (`--viewer-*`) | Docs (`--color-fd-*`) |
| --- | --- | --- | --- | --- | --- |
| canvas | `#F1F3F5` | `#1B1E26` | Page background | `canvas` | `background` |
| canvas-soft | `#E9EBED` | `#20242D` | Card / elevated surface / row hover | `canvas-soft`, `row-hover` | `muted` (`fd-card` local alias) |
| canvas-soft-2 | `#E1E5ED` | `#2B3041` | Active surface / secondary fill | `canvas-soft-2` | `secondary` |
| hairline | `#D2D6DF` | `#343948` | 1px divider / border ring | `hairline` | `border` |
| hairline-strong | `#979EB1` | `#5C6274` | Emphasized divider / phase chart mid-tone | `hairline-strong` | — |
| ink | `#14161F` | `#EEF0F6` | Headings / primary text | `ink` | `foreground` |
| body | `#4A4E5C` | `#9AA0B4` | Body copy | `body` | `muted-foreground` |
| mute | `#5E6376` | `#8A90A4` | Secondary labels / icons | `mute` | — |
| link | `#1B54E8` | `#5B7BFF` | Text links & focus rings (IKB; brightened in dark mode for text/rings only) | `link` | `primary`, `ring` |
| link-deep | `#001F73` | `#8AA0FF` | Link hover state | `link-deep` | — |
| cta | `#1B54E8` | `#1B54E8` | Primary CTA button fill (IKB in both themes; never use dark `link`) | `cta` | — |
| cta-deep | `#001F73` | `#001F73` | Primary CTA button hover fill | `cta-deep` | — |
| error | `#D40000` | `#FF5C5C` | Error foreground / danger border | `error` | — |
| error-soft | `#F7D4D6` | `#3B1414` | Solid error wash background (toasts/banners; non-transparent) | `error-soft` | — |
| warning | `#F5A623` | `#F5A623` | Warning foreground | `warning` | — |
| warning-soft | `#F4ECDE` | `#3A2E1D` | Solid warning wash background | `warning-soft` | — |
| link-soft | `#DAE2F6` | `#1E2645` | Solid IKB wash background (success / info toasts) | `link-soft` | — |
| star | `#E3B341` | `#F5C84C` | Starred favorite icon fill | `star` | — |
| nav-home | `#2F6E4A` | `#6FBF93` | Hub Home sidebar Lucide glyph only | `nav-home` | — |
| nav-datasets | `#187A8C` | `#5EC4D4` | Hub Datasets sidebar Lucide glyph only | `nav-datasets` | — |
| nav-leaderboard | `#7A3D62` | `#C88AA8` | Hub Leaderboard sidebar Lucide glyph only | `nav-leaderboard` | — |
| nav-plugins | `#9A5C16` | `#D4924A` | Hub Plugins sidebar Lucide glyph only | `nav-plugins` | — |
| nav-agents | `#5A4AA8` | `#A898E8` | Hub Agents sidebar Lucide glyph only | `nav-agents` | — |
| nav-models | `#5A6B38` | `#B4C47A` | Hub Models sidebar Lucide glyph only | `nav-models` | — |
| nav-inbox | `#B34A3C` | `#E08A7A` | Hub Inbox sidebar Lucide glyph only | `nav-inbox` | — |
| nav-orgs | `#3E5F7A` | `#8AA8C0` | Hub Organizations sidebar Lucide glyph only | `nav-orgs` | — |
| code-bg | `#E9EBED` | `#16181E` | Code well background (matches `canvas-soft` in light mode) | `code-bg` | — |
| accent(landing) | `#5B7BFF`(light)/ `#002FA7`(dark) | Same | Landing `--accent` / `--accent-deep` | — | — |

Landing `oklch(...)` surface declarations are exact perceptual equivalents of the canonical palette above; `shell-*` syntax highlighting variables are Viewer-local extensions.

---

## Typography

| Role | Font Stack | Usage Contract |
| --- | --- | --- |
| `sans` | `Geist` → `Inter` → `system-ui` → CJK (`Noto Sans SC` / `PingFang SC` / `Microsoft YaHei`) | All UI prose, navigation, table headers, and non-numeric table cells. Loaded via system/local stack in Hub/Viewer and `next/font` in `website/`. |
| `mono` | `Geist Mono` → `ui-monospace` → `Menlo` | Code blocks, CLI command bars, and tabular numbers (`tabular-nums`). |
| `display` | `Anton` (wordmark only) | Reserved strictly for brand wordmarks (hero and navbar logo); **never** used in prose or tool chrome. |

### Type scale rules
- `body-sm` (`14px` / `text-sm`) is the primary reading size for controls, table headers, and non-numeric cells.
- `caption` (`12px` / `text-xs`) is reserved for timestamps and secondary `mute` descriptions, never column headers.
- `PillTabs` (`11px`) is a documented compact in-panel exception.
- `figure` (`16px` / `20px`) is used for summary strip metrics on trajectory pages (status, score, started time, invocation count, and total tokens/timing).

---

## Geometry, Motion, Focus, and Elevation

1. **Border radius**: Three canonical tiers — `8px` (`sm` controls/buttons), `10px` (`md` inputs), and `14px` (`lg` cards, modals, popovers). Search scan inputs use `rounded-full` (stadium); landing hero CTA buttons may use `6px`. Never use `clip-path` corner bevels.
2. **Motion curves and libraries**:
   - Default transition: `--ease-smooth` `cubic-bezier(0.22, 1, 0.36, 1)` at `200ms`.
   - Documented curve exceptions: `--ease-spring` `cubic-bezier(0.34, 1.56, 0.64, 1)` (toast overshoot up to `550ms`, star burst, squish release up to `500ms`), `--ease-glide` `cubic-bezier(0.65, 0, 0.35, 1)` (`200ms` Liquid thumb geometry), and `--t-press` `80ms ease-out` (button press down).
   - Hub and Viewer use CSS transitions only, with two named runtime exceptions:
     1. `ThinkingLogo` (`apps/shared/components/thinking-logo.tsx`): 2D canvas point-cloud owl mark shown during list/detail loading (freezes on a static frame under `prefers-reduced-motion: reduce`).
     2. `liquid-gooey` (`Liquid` + `Liquid.Item` **Move** only, blur `3`, radius `8`): wraps `UnderlineTabs`, `PillTabs`, and Hub sidebar active rows (`canvas-soft-2` fill on tabs; `canvas` fill on sidebar). Never wrap Radix portals inside a Liquid group, and never import `liquid-gooey` in `website/`.
   - Landing page exceptions (`website/DESIGN.md`): one-shot hero stagger, `8px` view-timeline reveal (up to `400ms`), `OwlPixelMark` 2D canvas hero mark, and `signal-particles` background canvas (`pointer-events: none`; unmounted under `prefers-reduced-motion: reduce`).
   - Forbidden motion: magnetic cursors, cursor trails, 3D card tilt, infinite bobbing/spinning/pulsing on static icons, scroll-jacking.
3. **Role-based focus**:
   - **Buttons, links, and clickable cards**: `focus-visible:ring-2 ring-link/70` (`3px` outline on landing).
   - **Scan controls** (search bars, filter inputs, `Select` triggers): keep `1px hairline` border on focus without switching to IKB or adding a ring.
   - **Edit controls** (`FloatingLabel` inputs, form fields that write state): switch to `1px border-link` on focus without a ring.
4. **Selection and Elevation**:
   - `::selection` uses `28%` IKB wash across all three surfaces.
   - Popover/card elevation uses a single shadow token `--viewer-shadow-pop` (`0 1px 1px rgb(0 0 0 / 3%), 0 4px 8px -2px rgb(0 0 0 / 8%)` in light mode; `40% / 50%` opacity in dark mode) paired with a 4-sided `1px hairline` border.

---

## Component Vocabulary (SPA Chrome)

Always reuse shared components from `apps/shared/` before authoring custom primitives:

| Component / Pattern | Normative Rule |
| --- | --- |
| **Primary Button** (`Button` `default`) | `1px cta` border + `cta` fill (`#1B54E8` in both themes) + `rounded-[8px]` + `font-mono text-[13px] font-semibold` + `--viewer-shadow-pop` + `focus-visible:ring-2 ring-link/70`; hover shifts border and fill to `cta-deep`; `:active` applies `squish` (`scale(0.96)`). |
| **Secondary Button** (`Button` `outline` / `secondary`) | `1px hairline` border + `canvas` background + `ink` text; hover fades into `liquid-hover` (`canvas-soft`). |
| **Quiet Button** (`Button` `ghost`) | Borderless, `mute` text/icon, hover `liquid-hover` (`canvas-soft`) with `squish`. Standard icon button is `size="icon"` (`32px`); inline step actions use `size="iconSm"` (`20px` box, `14px` icon, `4px` radius). Callers pass layout classes only (`margin`, `shrink`, positioning) and never override `hover:`, `bg-*`, `border`, or `rounded-*`. |
| **Danger Button** (`danger` / `dangerOutline`) | Solid `danger`: `1px error` border + `error` fill (hover `error/80`). Outline `dangerOutline`: `1px hairline` + `canvas` (hover `error` text + `error/15` fill). Dropdown delete rows use `dropdownDangerItemClass`. |
| **Section Tabs** (`UnderlineTabs`) | `sans text-sm` with Liquid Move thumb (`canvas-soft-2` fill), one per page (except the Models plaza modality filter bar, which colors modality icons using existing `nav-*` tokens via `color-mix` with `canvas`). |
| **Compact In-Panel Tabs** (`PillTabs`) | `11px` Liquid Move tabs for in-panel switching; secondary mutually exclusive controls on the same view use `Select`. |
| **Segmented Control** (`SegmentedControl`) | `segmentGroupClass` / `segmentItemClass`, `8px` outer and inner radius, active `segmentOnClass` (`canvas-soft-2` + `ink`), inactive `segmentOffClass` (`text-body`, hover `canvas-soft`). |
| **Sidebar & Viewer Top-Bar Hover** | Because the surface background is already `canvas-soft`, use `sidebarHoverClass` (`hover:bg-canvas/50`, text to `ink`) instead of `quietHoverClass`. |
| **Text Links** | Internal routes use `INTERNAL_LINK_CLASS` (resting `ink`, hover underline + `link-deep`); external links and inline Sign-in actions use `EXTERNAL_LINK_CLASS` (resting `link`). |
| **File Tree Rows & Table Headers** | File tree rows use `treeRowClass` (`8px` radius, `text-sm`, active `canvas-soft-2`). Table sort headers use `SortableHead` (text transitions `mute` → `ink` without background fill). |
| **Chips & Meta Badges** | Static metadata tags use `metaChipClass` (`8px`, `hairline`, `text-xs`, `mute`). Interactive filter tags use `Chip` (`8px`, `hairline`, active `canvas-soft-2`, hover `canvas-soft`). |
| **Toasts, Selects, and Floating Labels** | Bottom-center overshoot Toast (`*-soft` solid background + `--viewer-shadow-pop`, used only for mutations lacking inline feedback). `Select` / `DropdownMenu` use `data-ageval-menu` + `scanTriggerClass` (`36px` height, `14px` popover radius) portaled to `document.body` / `OverlayRoot`. Edit inputs use `FloatingLabel` (`border-link` on focus). |
| **Catalog Cards vs. Tables** | Marketplace packages (`plugin`, `agent`) use 3-column `CatalogCard` (`14px` radius, 4-sided `hairline` + pop shadow, 3-line description, star count badge). Comparable rows (`dataset`, `jobs`, `leaderboard`, `members`, `models` catalog, and Agent Performance) use `hairline` tables (`canvas-soft` header, `canvas` body). |
| **Shells, Loading, and Empty States** | Hub shell: left `canvas-soft` sidebar + right `hairline`, opaque `canvas` top bar and main column (`xl` centered `w-[80%]`). Viewer shell: `canvas-soft` top bar + `canvas` main column. Loading state shows `ThinkingLogo` + `"Loading ..."` (never skeleton grids). Empty state centers a static icon + 1-line title + either a 1-line hint or 1 action control. |

---

## Ten Visual Invariants

1. **Hex locality**: Hex literals may appear only in the allowlisted token stylesheets and owl brand components (`HEX_ALLOWLIST` in `scripts/check_design_tokens.py`).
2. **IKB discipline**: IKB (`link` / `cta`) is reserved for links, focus rings/borders, primary CTAs, and brand marks — never large background fills (except the landing ink banner). Semantic status colors (`error`, `warning`, `star`) use their own tokens.
3. **Three-tier neutral hierarchy**: `canvas*` for surfaces, `hairline*` for borders/dividers, and `ink / body / mute` for typography (`mute` is never used for primary body prose).
4. **Wordmark-only display font**: `Anton` is restricted to brand wordmarks; all UI text uses the `sans` or `mono` stacks with CJK fallbacks and maximum `semibold` weight on Chinese headings.
5. **Unified radius tiers**: `8px` / `10px` / `14px` across all controls, inputs, and cards (plus `rounded-full` search bars and `6px` landing CTAs), with no `clip-path` bevels.
6. **Role-based focus visibility**: `2px` IKB ring on buttons/links/cards, `1px` IKB border on edit fields, and unchanged `1px hairline` border on scan/filter controls.
7. **Token-only interaction states**: Selection, hover, and active states reference semantic tokens or `color-mix` rather than ad-hoc hex/opacity literals.
8. **Bounded motion**: `200ms --ease-smooth` by default, plus the documented curve/canvas/Liquid exceptions; all animations respect `prefers-reduced-motion: reduce`.
9. **Three-tier iconography**: Owl marks for product branding, Lucide for UI actions, GitHub uploader avatars (or vendored `zju-real` / `brand-marks/assets/` Marks) for plugins/agents, and vendored model-pin SVGs for model labs.
10. **Single elevation shadow**: `--viewer-shadow-pop` with 4-sided `1px hairline` borders across all cards and popovers.

---

## Brand Assets Reference

| Asset | Source Location | Usage |
| --- | --- | --- |
| `OwlFlatMark` / `Icon` / `Peek` / `Plate` / `Lockup` / `Watermark` | `website/src/components/owl-flat.tsx` | Landing watermark, navbar, docs lockup, and brand plates (`paper`, `cream`, `ink`, `klein`). |
| `OwlIcon` | `apps/shared/components/owl-icon.tsx` | Hub and Viewer navigation brand mark (shares exact SVG path with `OwlFlatIcon`). |
| `ThinkingLogo` | `apps/shared/components/thinking-logo.tsx` | 2D canvas point-cloud loading indicator for Hub and Viewer. |
| Favicons | `website/src/app/favicon.ico`, `website/public/favicon.svg`, `apps/{hub,viewer}/public/favicon.{ico,svg}` | Black rounded plate with white owl face mark (`.ico` and `.svg` only). |
| Entity / Mechanism Marks | `apps/shared/lib/brand-marks/` | Plugin and Agent cards, details, and Leaderboards (defaults to uploader GitHub avatar or vendored `zju-real`). |
| Model Lab Marks | Vendored SVGs in the canonical model pin catalog | `/models` plaza and Agent model selectors (letter badge fallback when SVG is absent). |
