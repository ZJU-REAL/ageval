"""Regenerate executor option tables from frozen ``Options`` classes.

The tables in plugin READMEs and ``docs/design/16-model.md`` are generated.
``--check`` fails when a marker is missing or the body drifted.

    python scripts/gen_param_tables.py --write
    python scripts/gen_param_tables.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for extra in ("miniswe", "nooa", "dsh", "acp-oneshot", "terminus-2"):
    sys.path.insert(0, str(ROOT / "plugins" / extra / "src"))

from acp_oneshot_plugin.options import AcpOneshotOptions  # noqa: E402
from dsh_plugin.options import DshOptions  # noqa: E402
from miniswe_plugin.options import MinisweOptions  # noqa: E402
from nooa_plugin.options import NooaOptions  # noqa: E402
from terminus2_plugin.options import Terminus2Options  # noqa: E402

from ageval.plugins.contrib.acp.options import AcpOptions  # noqa: E402
from ageval.plugins.contrib.anthropic_http.options import AnthropicHTTPOptions  # noqa: E402
from ageval.plugins.contrib.openai_http.options import OpenAIHTTPOptions  # noqa: E402
from ageval.plugins.options import render_param_table  # noqa: E402

CLASSES: dict[str, type] = {
    "openai-http": OpenAIHTTPOptions,
    "anthropic-http": AnthropicHTTPOptions,
    "acp": AcpOptions,
    "miniswe": MinisweOptions,
    "terminus-2": Terminus2Options,
    "nooa": NooaOptions,
    "dsh": DshOptions,
    "acp-oneshot": AcpOneshotOptions,
}

# Every executor table is generated into the design page and that plugin's README.
SURFACES: dict[str, tuple[str, ...]] = {
    "openai-http": (
        "src/ageval/plugins/contrib/openai_http/README.md",
        "docs/design/16-model.md",
    ),
    "anthropic-http": (
        "src/ageval/plugins/contrib/anthropic_http/README.md",
        "docs/design/16-model.md",
    ),
    "acp": (
        "src/ageval/plugins/contrib/acp/README.md",
        "docs/design/16-model.md",
    ),
    "miniswe": (
        "plugins/miniswe/README.md",
        "docs/design/16-model.md",
    ),
    "terminus-2": (
        "plugins/terminus-2/README.md",
        "docs/design/16-model.md",
    ),
    "nooa": (
        "plugins/nooa/README.md",
        "docs/design/16-model.md",
    ),
    "dsh": (
        "plugins/dsh/README.md",
        "docs/design/16-model.md",
    ),
    "acp-oneshot": (
        "plugins/acp-oneshot/README.md",
        "docs/design/16-model.md",
    ),
}


def _block(executor_id: str) -> str:
    table = render_param_table(CLASSES[executor_id]).rstrip("\n")
    return (
        f"<!-- ageval:param-table executor={executor_id} -->\n{table}\n<!-- /ageval:param-table -->"
    )


def _replace(text: str, executor_id: str) -> tuple[str, bool]:
    start = f"<!-- ageval:param-table executor={executor_id} -->"
    end = "<!-- /ageval:param-table -->"
    begin = text.find(start)
    if begin < 0:
        return text, False
    finish = text.find(end, begin)
    if finish < 0:
        return text, False
    finish += len(end)
    updated = text[:begin] + _block(executor_id) + text[finish:]
    return updated, updated != text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    missing: list[str] = []
    drifted: list[str] = []
    for executor_id, paths in SURFACES.items():
        for relative in paths:
            path = ROOT / relative
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            updated, changed = _replace(text, executor_id)
            marker = f"{relative} ({executor_id})"
            if f"<!-- ageval:param-table executor={executor_id} -->" not in text:
                missing.append(marker)
                continue
            if "<!-- /ageval:param-table -->" not in text:
                missing.append(marker)
                continue
            if args.write and changed:
                path.write_text(updated, encoding="utf-8")
            elif args.check and changed:
                drifted.append(marker)
    if missing or drifted:
        for item in missing:
            print(f"missing marker: {item}", file=sys.stderr)
        for item in drifted:
            print(f"drift: {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
