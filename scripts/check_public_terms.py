#!/usr/bin/env python3
"""Flag Avoid terms on public copy. Authority: docs/glossary.md."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_GLOBS = (
    "README.md",
    "README.zh-CN.md",
    "website/content/**/*.mdx",
    "website/src/components/landing/copy.ts",
    "examples/**/README.md",
    "examples/**/README.zh-CN.md",
)

# Whole-phrase bans. CLI flags and forbidden-field teaching are skipped per line.
BANNED = (
    "题包",
    "一等评测维度",
    "first-class eval",
    "first-class evaluation",
    "harness 之下",
    "harness beneath",
    "硬顶",
    "独占槽",
    "exclusive-slot",
    "exclusive slot",
    "按名注入",
    "盒子",
    "可见 Attempt",
    "job 文档",
    "job document",
    r"(?<!-)task package(?!s)",
    "NARROW SURFACE",
    "设计口令",
    "契约薄",
    "实现可胖",
    "实现自由",
    "fail-closed",
    "fail closed",
    "fail-open",
    "host-loop",
    "in-box",
    "in-image",
    "机制卡",
    "字段糖",
    "硬切",
    "一层 C",
    "层 C",
    "探测管子",
    "密封轨迹",
    "oneshot",
    "证据等级",
    "evidence grade",
    "evidence-grade",
    r"([^-]|\b)slots?\b",
    "槽",
)

# Banned only in Chinese-facing files. EN pages and path literals (gold.json,
# evaluation/gold) keep these words; landing copy.ts mixes zh and en in one
# file, so it is outside this channel.
ZH_ONLY_BANNED = (r"\bgold\b",)
ZH_ONLY_ALLOW_IF_LINE_HAS = ("gold.json", "evaluation/gold")

# These fire only when not part of a longer allowed token.
SOFT = (
    ("赢家", ("赢家",)),
    ("相位", ("相位",)),
)

ALLOW_IF_LINE_HAS = (
    "provider.kind",
    "--kind",
    "deepseek-harness",
    "kind: port",
    "kind:port",
    "acp-oneshot",
    "slots.py",
    "replace-slot",
    "slots:",
)


def iter_public_files() -> list[Path]:
    out: list[Path] = []
    for g in PUBLIC_GLOBS:
        out.extend(ROOT.glob(g))
    return sorted({p for p in out if p.is_file()})


def line_allowed(line: str) -> bool:
    return any(tok in line for tok in ALLOW_IF_LINE_HAS)


def is_zh_facing(path: Path) -> bool:
    name = path.name
    return ".zh-CN." in name


def main() -> int:
    hits: list[str] = []
    for path in iter_public_files():
        rel = path.relative_to(ROOT)
        zh_facing = is_zh_facing(path)
        for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line_allowed(raw):
                continue
            for phrase in BANNED:
                pat = phrase if phrase.startswith("(?") or phrase.startswith(r"(") else re.escape(phrase)
                if re.search(pat, raw):
                    hits.append(f"{rel}:{i}: {phrase!r}")
            for phrase, _ in SOFT:
                if phrase in raw:
                    hits.append(f"{rel}:{i}: {phrase!r}")
            if zh_facing and not any(tok in raw for tok in ZH_ONLY_ALLOW_IF_LINE_HAS):
                for phrase in ZH_ONLY_BANNED:
                    if re.search(phrase, raw):
                        hits.append(f"{rel}:{i}: {phrase!r} (zh-only)")
    if hits:
        print("public copy still uses glossary Avoid terms:")
        print("\n".join(hits))
        return 1
    print(f"ok ({len(iter_public_files())} public files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
