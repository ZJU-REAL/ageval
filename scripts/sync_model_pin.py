#!/usr/bin/env python3
"""Pin models.dev (plus extra gateway prefixes) for Hub encyclopedia.

Maintainer/script only. Hub / Registry / CI request paths must not curl these
hosts. Run: python3 scripts/sync_model_pin.py

Slim rows keep models.dev modalities, knowledge, temperature, structured
output, and unioned api.json reasoning_options. Logos: --logos-only.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN_DIR = REPO / "apps/hub/src/lib/model-pin"
LOGO_DIR = REPO / "apps/hub/public/model-pin/logos"

MODELS_URL = "https://models.dev/models.json"
API_URL = "https://models.dev/api.json"
LAB_LOGO_URL = "https://models.dev/logos/labs/{lab}.svg"
LOBE_SVG_URL = "https://unpkg.com/@lobehub/icons-static-svg@latest/icons/{slug}.svg"
# docs/13 ink (light). Baked into pin SVGs so <img> currentColor is not black-on-dark.
INK_FILL = "#14161F"
PLACEHOLDER_NEEDLE = "9.8132 15.9038"

# Keep in lockstep with apps/hub/src/lib/model-pin/lab-marks.ts.
# These labs reuse Hub brand-marks at render; do not vendor a pin SVG.
LAB_BRAND_MARK = {
    "alibaba": "qwen",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "google": "gemini",
    "minimax": "minimax",
    "moonshotai": "kimi",
    "openai": "openai",
    "xai": "grok",
    "zhipuai": "zhipu",
}

# Remaining labs: vendor Lobe *static* color SVG (not the npm runtime).
LOBE_COLOR_SLUG = {
    "arcee-ai": "arcee-color",
    "bytedance-seed": "doubao-color",
    "cohere": "cohere-color",
    "meituan": "longcat-color",
    "meta": "meta-color",
    "microsoft": "microsoft-color",
    "mistral": "mistral-color",
    "nvidia": "nvidia-color",
    "perplexity": "perplexity-color",
    "poolside": "poolside-color",
    "stepfun": "stepfun-color",
    "tencent": "hunyuan-color",
    "upstage": "upstage-color",
}

# Mono Lobe marks we still want as identity (baked ink + white plate).
LOBE_INK_SLUG = {
    "ibm": "ibm",
}

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# Gateways used in ageval overlays that are not models.dev provider ids.
EXTRA_PREFIXES = ("dashscope", "dashscope-", "litellm")

# Labs omitted from pin.json. models.dev still lists them; we just do not pin.
SKIP_LABS = frozenset({
    "aisingapore",
    "amazon",
    "arcee-ai",
    "deepreinforce",
    "inclusionai",
    "openbmb",
    "poolside",
    "sakana",
    "sarvam",
    "sdaia",
    "swiss-ai",
    "trendyol",
    "upstage",
    "writer",
})

LAB_NAMES = {
    "aisingapore": "AI Singapore",
    "alibaba": "Alibaba",
    "anthropic": "Anthropic",
    "arcee-ai": "Arcee",
    "bytedance-seed": "ByteDance Seed",
    "cohere": "Cohere",
    "deepreinforce": "DeepReinforce",
    "deepseek": "DeepSeek",
    "google": "Google",
    "ibm": "IBM",
    "inclusionai": "InclusionAI",
    "meituan": "Meituan",
    "meta": "Meta",
    "microsoft": "Microsoft",
    "minimax": "MiniMax",
    "mistral": "Mistral",
    "moonshotai": "Moonshot",
    "nvidia": "NVIDIA",
    "openai": "OpenAI",
    "perplexity": "Perplexity",
    "poolside": "Poolside",
    "sakana": "Sakana",
    "sarvam": "Sarvam",
    "sdaia": "SDAIA",
    "stepfun": "StepFun",
    "swiss-ai": "Swiss AI",
    "tencent": "Tencent",
    "thinkingmachines": "Thinking Machines",
    "trendyol": "Trendyol",
    "upstage": "Upstage",
    "xai": "xAI",
    "xiaomi": "Xiaomi",
    "zhipuai": "Zhipu AI",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ageval-model-pin"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _add_lookup(lookup: dict[str, list[str]], key: str, canonical: str) -> None:
    text = (key or "").strip()
    if not text:
        return
    bucket = lookup.setdefault(text, [])
    if canonical not in bucket:
        bucket.append(canonical)


def _hf_weights(raw: object) -> str | None:
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if "huggingface.co/" in url:
            return url
    return None


EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _merge_reasoning_options(acc: dict[str, set[str]], raw: object) -> None:
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").strip()
        if not typ:
            continue
        bucket = acc.setdefault(typ, set())
        vals = item.get("values")
        if not isinstance(vals, list):
            continue
        for value in vals:
            if isinstance(value, (str, int, float)):
                text = str(value).strip()
                if text:
                    bucket.add(text)


def _finalize_reasoning_options(acc: dict[str, set[str]]) -> list[dict]:
    out: list[dict] = []
    for typ in sorted(acc):
        row: dict = {"type": typ}
        values = acc[typ]
        if values:
            def sort_key(value: str) -> tuple[int, str]:
                try:
                    return (0, f"{EFFORT_ORDER.index(value):02d}")
                except ValueError:
                    return (1, value)

            row["values"] = sorted(values, key=sort_key)
        out.append(row)
    return out


def _map_provider_model(
    provider_id: str,
    model_id: str,
    canonicals: set[str],
    leaves: dict[str, list[str]],
) -> str | None:
    mid = (model_id or "").strip()
    if not mid:
        return None
    if mid.startswith("~"):
        mid = mid[1:]
    if ":" in mid:
        base, _tag = mid.rsplit(":", 1)
        if base in canonicals:
            return base
    if mid in canonicals:
        return mid
    prefixed = f"{provider_id}/{mid}"
    if prefixed in canonicals:
        return prefixed
    leaf = mid.rsplit("/", 1)[-1]
    hits = leaves.get(leaf) or []
    if len(hits) == 1:
        return hits[0]
    return None


MODALITY_VALUES = ("text", "audio", "image", "video", "pdf")


def _modalities(row: dict) -> dict[str, list[str]]:
    raw = row.get("modalities") if isinstance(row.get("modalities"), dict) else {}

    def take(side: str) -> list[str]:
        items = raw.get(side)
        if not isinstance(items, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            if item in MODALITY_VALUES and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    inn = take("input")
    out = take("output")
    if not inn and not out:
        return {"input": ["text"], "output": ["text"]}
    return {"input": inn, "output": out}


def _litellm_price(row: object) -> dict[str, float] | None:
    if not isinstance(row, dict):
        return None
    inp = row.get("input_cost_per_token")
    out = row.get("output_cost_per_token")
    if not isinstance(inp, (int, float)) or not isinstance(out, (int, float)):
        return None
    return {"input": round(float(inp) * 1_000_000, 6), "output": round(float(out) * 1_000_000, 6)}


def build_pin(models: dict, api: dict, litellm: dict | None) -> dict:
    canonicals = {
        cid
        for cid in models
        if isinstance(cid, str)
        and "/" in cid
        and cid.split("/", 1)[0] not in SKIP_LABS
    }
    leaves: dict[str, list[str]] = {}
    for cid in sorted(canonicals):
        leaf = cid.rsplit("/", 1)[-1]
        leaves.setdefault(leaf, []).append(cid)

    labs: dict[str, dict[str, str]] = {}
    slim_models: dict[str, dict] = {}
    lookup: dict[str, list[str]] = {}
    prices: dict[str, dict[str, dict[str, float]]] = {}
    reasoning_acc: dict[str, dict[str, set[str]]] = {}

    for cid in sorted(canonicals):
        row = models.get(cid) or {}
        if not isinstance(row, dict):
            continue
        lab = cid.split("/", 1)[0]
        labs[lab] = {
            "name": LAB_NAMES.get(lab, lab),
            "logo": "",
        }
        limit = row.get("limit") if isinstance(row.get("limit"), dict) else {}
        slim: dict = {
            "name": str(row.get("name") or cid.rsplit("/", 1)[-1]),
            "description": str(row.get("description") or ""),
            "family": str(row.get("family") or ""),
            "lab": lab,
            "release_date": str(row.get("release_date") or ""),
            "last_updated": str(row.get("last_updated") or ""),
            "knowledge": str(row.get("knowledge") or ""),
            "context": limit.get("context"),
            "output": limit.get("output"),
            "input_limit": limit.get("input"),
            "open_weights": bool(row.get("open_weights")),
            "reasoning": bool(row.get("reasoning")),
            "tool_call": bool(row.get("tool_call")),
            "attachment": bool(row.get("attachment")),
            "temperature": bool(row.get("temperature")),
            "modalities": _modalities(row),
            "weights": _hf_weights(row.get("weights")),
            "reasoning_options": [],
        }
        if "structured_output" in row:
            slim["structured_output"] = bool(row.get("structured_output"))
        slim_models[cid] = slim
        _add_lookup(lookup, cid, cid)
        _add_lookup(lookup, cid.rsplit("/", 1)[-1], cid)

    prefixes = set(EXTRA_PREFIXES)
    for provider_id, provider in api.items():
        if not isinstance(provider_id, str) or not isinstance(provider, dict):
            continue
        prefixes.add(provider_id)
        for mid, mrow in (provider.get("models") or {}).items():
            if not isinstance(mid, str):
                continue
            canonical = _map_provider_model(provider_id, mid, canonicals, leaves)
            if canonical is None:
                continue
            _add_lookup(lookup, mid, canonical)
            if isinstance(mrow, dict):
                _merge_reasoning_options(
                    reasoning_acc.setdefault(canonical, {}),
                    mrow.get("reasoning_options"),
                )
            cost = mrow.get("cost") if isinstance(mrow, dict) else None
            if isinstance(cost, dict) and isinstance(cost.get("input"), (int, float)):
                bucket = prices.setdefault(canonical, {})
                bucket[provider_id] = {
                    "input": float(cost["input"]),
                    "output": float(cost["output"]) if isinstance(cost.get("output"), (int, float)) else 0.0,
                }

    for cid, acc in reasoning_acc.items():
        model = slim_models.get(cid)
        if model is not None:
            model["reasoning_options"] = _finalize_reasoning_options(acc)

    if isinstance(litellm, dict):
        for key, row in litellm.items():
            if not isinstance(key, str) or key.startswith("sample_"):
                continue
            canonical = key if key in canonicals else None
            if canonical is None:
                hits = lookup.get(key) or []
                if len(hits) == 1:
                    canonical = hits[0]
            if canonical is None:
                continue
            if prices.get(canonical):
                continue
            litellm_cost = _litellm_price(row)
            if litellm_cost is None:
                continue
            prices[canonical] = {"litellm": litellm_cost}

    prefix_list = sorted(prefixes, key=lambda p: (-len(p), p))
    return {
        "format": "ageval.model-pin/1",
        "source": "models.dev",
        "pinned_at": date.today().isoformat(),
        "labs": {k: labs[k] for k in sorted(labs)},
        "models": slim_models,
        "prefixes": prefix_list,
        "lookup": {k: lookup[k] for k in sorted(lookup)},
        "prices": {k: prices[k] for k in sorted(prices)},
        "aliases": {},
    }


def _try_get(url: str) -> bytes | None:
    try:
        return _get(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def _is_placeholder(svg: str) -> bool:
    return PLACEHOLDER_NEEDLE in svg


def _bake_ink(svg: str) -> str:
    text = svg
    text = re.sub(r'fill="currentColor"', f'fill="{INK_FILL}"', text, flags=re.I)
    text = re.sub(r"fill='currentColor'", f"fill='{INK_FILL}'", text, flags=re.I)
    text = re.sub(r'stroke="currentColor"', f'stroke="{INK_FILL}"', text, flags=re.I)
    text = re.sub(r"stroke='currentColor'", f"stroke='{INK_FILL}'", text, flags=re.I)
    text = re.sub(r"fill:\s*currentColor", f"fill:{INK_FILL}", text, flags=re.I)
    text = re.sub(r"stroke:\s*currentColor", f"stroke:{INK_FILL}", text, flags=re.I)
    return text


def _has_hex_paint(svg: str) -> bool:
    return bool(re.search(r"#[0-9A-Fa-f]{3,8}\b", svg))


def resolve_lab_logo(lab: str) -> tuple[str, str, bytes | None]:
    """Return (logo filename or '', tone, svg bytes or None)."""
    if lab in LAB_BRAND_MARK:
        return "", "", None
    slug = LOBE_COLOR_SLUG.get(lab)
    if slug:
        raw = _try_get(LOBE_SVG_URL.format(slug=slug))
        if raw:
            text = raw.decode("utf-8", "replace")
            if not _is_placeholder(text):
                return f"{lab}.svg", "color", raw
    ink_slug = LOBE_INK_SLUG.get(lab)
    if ink_slug:
        raw = _try_get(LOBE_SVG_URL.format(slug=ink_slug))
        if raw:
            text = raw.decode("utf-8", "replace")
            if not _is_placeholder(text):
                return f"{lab}.svg", "ink", _bake_ink(text).encode("utf-8")
    raw = _try_get(LAB_LOGO_URL.format(lab=lab))
    if raw:
        text = raw.decode("utf-8", "replace")
        if not _is_placeholder(text):
            if _has_hex_paint(text) and "currentColor" not in text:
                return f"{lab}.svg", "color", raw
            return f"{lab}.svg", "ink", _bake_ink(text).encode("utf-8")
    return "", "", None


def write_logos(labs: dict[str, dict]) -> dict[str, int]:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"brand": 0, "color": 0, "ink": 0, "letter": 0}
    wanted: set[str] = set()
    for lab, row in labs.items():
        filename, tone, data = resolve_lab_logo(lab)
        row["logo"] = filename
        if tone:
            row["tone"] = tone
        else:
            row.pop("tone", None)
        dest = LOGO_DIR / f"{lab}.svg"
        if filename and data is not None:
            dest.write_bytes(data)
            wanted.add(dest.name)
            counts["color" if tone == "color" else "ink"] += 1
        else:
            if dest.exists():
                dest.unlink()
            if lab in LAB_BRAND_MARK:
                counts["brand"] += 1
            else:
                counts["letter"] += 1
    for leftover in LOGO_DIR.glob("*.svg"):
        if leftover.name not in wanted:
            leftover.unlink()
    return counts


def _write_pin(pin: dict) -> None:
    PIN_DIR.mkdir(parents=True, exist_ok=True)
    (PIN_DIR / "pin.json").write_text(
        json.dumps(pin, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    logos_only = "--logos-only" in sys.argv
    if logos_only:
        pin_path = PIN_DIR / "pin.json"
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        if not isinstance(pin, dict) or not isinstance(pin.get("labs"), dict):
            raise SystemExit("pin.json missing labs")
        for lab, row in pin["labs"].items():
            if isinstance(row, dict) and "name" not in row:
                row["name"] = LAB_NAMES.get(lab, lab)
        counts = write_logos(pin["labs"])
        _write_pin(pin)
        print(
            "logos-only "
            f"brand={counts['brand']} color={counts['color']} "
            f"ink={counts['ink']} letter={counts['letter']}"
        )
        return 0

    models = json.loads(_get(MODELS_URL).decode("utf-8"))
    api = json.loads(_get(API_URL).decode("utf-8"))
    if not isinstance(models, dict) or not isinstance(api, dict):
        raise SystemExit("models.dev payload is not an object")
    litellm: dict | None = None
    try:
        litellm = json.loads(_get(LITELLM_URL).decode("utf-8"))
    except Exception:
        litellm = None
    pin = build_pin(models, api, litellm)
    counts = write_logos(pin["labs"])
    _write_pin(pin)
    print(
        f"pinned {len(pin['models'])} models, {len(pin['labs'])} labs, "
        f"{len(pin['lookup'])} lookup keys → {PIN_DIR / 'pin.json'}"
    )
    if SKIP_LABS:
        print("skipped labs: " + ", ".join(sorted(SKIP_LABS)))
    print(
        "logos "
        f"brand={counts['brand']} color={counts['color']} "
        f"ink={counts['ink']} letter={counts['letter']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
