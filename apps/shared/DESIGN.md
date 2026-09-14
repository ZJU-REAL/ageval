---
# Shared Hub / Viewer theme constants. Must match docs/design/13-web-ui-tokens.md
# (machine-checked). Hub / Viewer inherit this listing — do not fork a second palette.
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
    code-bg: "#E9EBED"
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

# SPA token listing

Constitution: [`docs/design/13-web-ui-tokens.md`](../../docs/design/13-web-ui-tokens.md).
This YAML is the Hub / Viewer token listing (machine-checked). Do not fork a second palette.

Product Taste stays in [`apps/hub/DESIGN.md`](../hub/DESIGN.md) (catalog) and [`apps/viewer/DESIGN.md`](../viewer/DESIGN.md) (local Jobs). This file does not inventory routes or chrome.
