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

# Whole-phrase bans on public surfaces. CLI flags and forbidden-field teaching are skipped per line.
BANNED = (
    "题包",
    "证据包",
    "金标",
    "一等评测维度",
    "first-class eval",
    "first-class evaluation",
    "harness 之下",
    "harness beneath",
    "硬顶",
    "hard ceiling",
    "hard ceilings",
    "赢家",
    "exclusive-slot winner",
    "exclusive winner",
    "相位",
    "盒子",
    "箱子",
    "打分盒",
    "scoring box",
    "agent box",
    "Attempt box",
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
    "层 B",
    r"\blayer[- ]?[BC]\b",
    "观察袋",
    "插件袋",
    "探测管子",
    "密封轨迹",
    "oneshot",
    "证据等级",
    "evidence grade",
    "evidence-grade",
    "勾选机",
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


def main() -> int:
    hits: list[str] = []
    for path in iter_public_files():
        rel = path.relative_to(ROOT)
        for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line_allowed(raw):
                continue
            for phrase in BANNED:
                pat = (
                    phrase
                    if phrase.startswith("(?")
                    or phrase.startswith(r"(")
                    or phrase.startswith(r"\b")
                    else re.escape(phrase)
                )
                if re.search(pat, raw, flags=re.IGNORECASE if phrase.isascii() else 0):
                    hits.append(f"{rel}:{i}: {phrase!r}")
    if hits:
        print("public copy still uses glossary Avoid terms:")
        print("\n".join(hits))
        return 1
    print(f"ok ({len(iter_public_files())} public files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
