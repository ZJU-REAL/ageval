"""Drop BuildKit HTTP(S)_PROXY for pip when official base wrote /etc/pip.conf.

Pip prefers env over config, so pip.conf cannot beat a dead ``HTTP_PROXY``
injected into every ``RUN``. Auto-applies only when imported as
``sitecustomize`` (site hook). Empty ``AGEVAL_PIP_INDEX`` does not install this
file, so official PyPI is unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

_CONF = Path("/etc/pip.conf")
_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def index_url_from_pip_conf(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("index-url"):
            _, _, value = stripped.partition("=")
            return value.strip()
    return ""


def apply_pip_mirror_env(
    *,
    conf: Path = _CONF,
    environ: dict[str, str] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    if not conf.is_file():
        return
    index = index_url_from_pip_conf(conf.read_text(encoding="utf-8"))
    if index and not (env.get("PIP_INDEX_URL") or "").strip():
        env["PIP_INDEX_URL"] = index
    for key in _PROXY_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"


if __name__ == "sitecustomize":
    apply_pip_mirror_env()
