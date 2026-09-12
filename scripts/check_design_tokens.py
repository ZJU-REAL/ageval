#!/usr/bin/env python3
"""Machine-check web UI tokens against docs/design/13-web-ui-tokens.md.

Checks:
  1. Doc table and the CANONICAL dict in this script agree (both directions).
  2. apps/viewer/DESIGN.md YAML lists the same SPA tokens (Hub inherits that file).
  3. Mapped CSS variables in the three apps only ever hold canonical values.
  4. No raw hex outside the token/theme files and owl brand assets.

Run: python3 scripts/check_design_tokens.py  (exit 1 on any failure)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs/design/13-web-ui-tokens.md"
SPA_DESIGN = REPO / "apps/viewer/DESIGN.md"
SPA_SKIP = {"accent"}  # landing-only; not in Hub/Viewer YAML

# token -> (light, dark)
CANONICAL: dict[str, tuple[str, str]] = {
    "canvas": ("#F1F3F5", "#1B1E26"),
    "canvas-soft": ("#E9EBED", "#20242D"),
    "canvas-soft-2": ("#E1E5ED", "#2B3041"),
    "hairline": ("#D2D6DF", "#343948"),
    "hairline-strong": ("#979EB1", "#5C6274"),
    "ink": ("#14161F", "#EEF0F6"),
    "body": ("#4A4E5C", "#9AA0B4"),
    "mute": ("#5E6376", "#8A90A4"),
    "link": ("#1B54E8", "#5B7BFF"),
    "link-deep": ("#001F73", "#8AA0FF"),
    "error": ("#D40000", "#FF5C5C"),
    "error-soft": ("#F7D4D6", "#3B1414"),
    "warning": ("#F5A623", "#F5A623"),
    "warning-soft": ("#F4ECDE", "#3A2E1D"),
    "link-soft": ("#DAE2F6", "#1E2645"),
    "star": ("#E3B341", "#F5C84C"),
    "nav-home": ("#2F6E4A", "#6FBF93"),
    "nav-datasets": ("#187A8C", "#5EC4D4"),
    "nav-leaderboard": ("#7A3D62", "#C88AA8"),
    "nav-plugins": ("#9A5C16", "#D4924A"),
    "nav-agents": ("#5A4AA8", "#A898E8"),
    "nav-models": ("#5A6B38", "#B4C47A"),
    "nav-inbox": ("#B34A3C", "#E08A7A"),
    "nav-orgs": ("#3E5F7A", "#8AA8C0"),
    "code-bg": ("#F1F3F5", "#16181E"),
    "accent": ("#5B7BFF", "#002FA7"),
}

# (file, css var, canonical token, required)
VAR_MAP: list[tuple[str, str, str, bool]] = [
    # hub / viewer (identical --viewer-* vocabulary, values checked per file)
    *(
        (f"apps/{app}/src/index.css", f"--viewer-{var}", token, True)
        for app in ("hub", "viewer")
        for var, token in [
            ("canvas", "canvas"),
            ("canvas-soft", "canvas-soft"),
            ("canvas-soft-2", "canvas-soft-2"),
            ("hairline", "hairline"),
            ("hairline-strong", "hairline-strong"),
            ("ink", "ink"),
            ("body", "body"),
            ("mute", "mute"),
            ("link", "link"),
            ("link-deep", "link-deep"),
            ("error", "error"),
            ("error-soft", "error-soft"),
            ("warning", "warning"),
            ("warning-soft", "warning-soft"),
            ("link-soft", "link-soft"),
            ("star", "star"),
            ("nav-home", "nav-home"),
            ("nav-datasets", "nav-datasets"),
            ("nav-leaderboard", "nav-leaderboard"),
            ("nav-plugins", "nav-plugins"),
            ("nav-agents", "nav-agents"),
            ("nav-models", "nav-models"),
            ("nav-inbox", "nav-inbox"),
            ("nav-orgs", "nav-orgs"),
            ("code-bg", "code-bg"),
            ("row-hover", "canvas-soft"),
        ]
    ),
    # docs (fumadocs vars + prose link vars)
    ("website/src/app/global.css", "--color-fd-background", "canvas", True),
    ("website/src/app/global.css", "--color-fd-foreground", "ink", True),
    ("website/src/app/global.css", "--color-fd-muted", "canvas-soft", True),
    ("website/src/app/global.css", "--color-fd-muted-foreground", "body", True),
    ("website/src/app/global.css", "--color-fd-secondary", "canvas-soft-2", True),
    ("website/src/app/global.css", "--color-fd-primary", "link", True),
    ("website/src/app/global.css", "--color-fd-ring", "link", True),
    ("website/src/app/global.css", "--color-fd-border", "hairline", True),
    ("website/src/app/global.css", "--ageval-link", "link", True),
    ("website/src/app/global.css", "--ageval-link-deep", "link-deep", True),
    # landing accents
    ("website/src/components/landing/landing.css", "--accent", "accent", True),
    ("website/src/components/landing/landing.css", "--accent-deep", "accent", True),
]

# Hex literals are allowed only in these files (token definitions + owl assets).
HEX_ALLOWLIST = {
    "website/src/app/global.css",
    "website/src/components/landing/landing.css",
    "apps/hub/src/index.css",
    "apps/viewer/src/index.css",
    "website/src/components/owl-flat.tsx",
    "apps/hub/src/components/owl-icon.tsx",
    "apps/viewer/src/components/owl-icon.tsx",
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
ASSIGN_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def norm(hexes: list[str]) -> set[str]:
    return {h.lower() for h in hexes}


def check_doc(errors: list[str]) -> None:
    text = DOC.read_text(encoding="utf-8")
    section = re.search(r"## 色彩令牌\n(.*?)\n## ", text, re.S)
    if not section:
        errors.append("doc: '## 色彩令牌' section not found")
        return
    doc_tokens: dict[str, set[str]] = {}
    for line in section.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("令牌", "---", ":---") or set(cells[0]) <= {"-", ":"}:
            continue
        name = re.sub(r"（.*?）|\(.*?\)", "", cells[0]).replace("`", "").strip()
        doc_tokens[name] = norm(HEX_RE.findall(line))
    missing = set(CANONICAL) - set(doc_tokens)
    extra = set(doc_tokens) - set(CANONICAL)
    if missing:
        errors.append(f"doc: tokens missing from table: {sorted(missing)}")
    if extra:
        errors.append(f"doc: unknown tokens in table: {sorted(extra)}")
    for name, hexes in doc_tokens.items():
        want = norm(list(CANONICAL.get(name, ())))
        absent = want - hexes
        if absent:
            errors.append(f"doc: row '{name}' lacks canonical value(s) {sorted(absent)}")


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
YAML_HEX_RE = re.compile(r"^\s+([a-z0-9-]+):\s*\"(#[0-9A-Fa-f]{6})\"\s*$")


def check_spa_design(errors: list[str]) -> None:
    """Viewer DESIGN.md YAML is the SPA-facing token listing (Hub inherits it)."""
    if not SPA_DESIGN.is_file():
        errors.append("apps/viewer/DESIGN.md: missing")
        return
    text = SPA_DESIGN.read_text(encoding="utf-8")
    block = FRONTMATTER_RE.match(text)
    if not block:
        errors.append("apps/viewer/DESIGN.md: missing YAML frontmatter token listing")
        return
    found: dict[str, set[str]] = {}
    for line in block.group(1).splitlines():
        m = YAML_HEX_RE.match(line)
        if not m:
            continue
        found.setdefault(m.group(1), set()).add(m.group(2).lower())
    for name, pair in CANONICAL.items():
        if name in SPA_SKIP:
            continue
        have = found.get(name, set())
        want = norm(list(pair))
        if name not in found:
            errors.append(f"apps/viewer/DESIGN.md: token '{name}' missing from YAML")
            continue
        absent = want - have
        extra = have - want
        if absent:
            errors.append(
                f"apps/viewer/DESIGN.md: '{name}' lacks canonical value(s) {sorted(absent)}"
            )
        if extra:
            errors.append(
                f"apps/viewer/DESIGN.md: '{name}' has non-canonical value(s) {sorted(extra)}"
            )


def check_vars(errors: list[str]) -> None:
    by_file: dict[str, dict[str, set[str]]] = {}
    for rel, var, _token, _req in VAR_MAP:
        if rel not in by_file:
            assigns: dict[str, set[str]] = {}
            for m in ASSIGN_RE.finditer((REPO / rel).read_text(encoding="utf-8")):
                assigns.setdefault(m.group(1), set()).update(norm(HEX_RE.findall(m.group(2))))
            by_file[rel] = assigns
        values = by_file[rel].get(var)
        if values is None:
            errors.append(f"{rel}: variable {var} not defined")
            continue
        token = next(t for f, v, t, _ in VAR_MAP if f == rel and v == var)
        allowed = norm(list(CANONICAL[token]))
        bad = values - allowed
        if bad:
            errors.append(f"{rel}: {var} holds non-canonical {sorted(bad)} (token '{token}' allows {sorted(allowed)})")


def check_raw_hex(errors: list[str]) -> None:
    for root in ("website/src", "apps/hub/src", "apps/viewer/src"):
        for path in (REPO / root).rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".css"} or not path.is_file():
                continue
            rel = path.relative_to(REPO).as_posix()
            if rel in HEX_ALLOWLIST:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if HEX_RE.search(line):
                    errors.append(f"{rel}:{i}: raw hex outside token files: {HEX_RE.search(line).group(0)}")


def main() -> int:
    errors: list[str] = []
    check_doc(errors)
    check_spa_design(errors)
    check_vars(errors)
    check_raw_hex(errors)
    if errors:
        print("design-token check FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("design-token check OK (doc + hub/viewer + website in sync)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
