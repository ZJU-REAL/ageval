#!/usr/bin/env python3
"""In-container nooa worker — NVIDIA OO Agents + real LLM.

Reads one JSON object from argv[1] or stdin. Credentials arrive via env
(OPENAI_API_KEY / OPENAI_BASE_URL), not the payload::

    {
      "prompt": "...",
      "agent": "lib.agents:JsonlAggAgent",
      "method": "run",
      "model": "openai/glm-5.2",
      "api_base": "https://…/v1",
      "package_root": "/attempt/package",
      "workdir": "/attempt/workspace"
    }

Writes one AgentResult-shaped JSON object to stdout.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path("/opt/nooa")
if _PLUGIN_ROOT.is_dir() and str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_http_loopback(url: str | None) -> bool:
    try:
        from ageval.plugins.http_loopback import is_http_loopback

        return is_http_loopback(url)
    except ImportError:
        from urllib.parse import urlparse

        text = str(url or "").strip()
        if not text:
            return False
        parsed = urlparse(text if "://" in text else f"http://{text}")
        host = (parsed.hostname or "").lower()
        return host in _LOOPBACK_HOSTS


def _load_agent_class(agent_ref: str, package_root: Path) -> Any:
    import importlib.util

    if ":" in agent_ref:
        mod_name, cls_name = agent_ref.split(":", 1)
    else:
        mod_name, cls_name = agent_ref, None
    root = package_root.expanduser().resolve(strict=False)
    rel = Path(*mod_name.split("."))
    for candidate in (root / f"{rel}.py", root / rel / "__init__.py"):
        if not candidate.is_file():
            continue
        unique = f"nooa_pkg_{abs(hash(str(root)))}_{mod_name.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(unique, candidate)
        if spec is None or spec.loader is None:
            continue
        loaded = importlib.util.module_from_spec(spec)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        sys.modules[unique] = loaded
        spec.loader.exec_module(loaded)
        if cls_name:
            cls = getattr(loaded, cls_name, None)
            if cls is None:
                raise RuntimeError(f"nooa_agent_class_missing:{cls_name}")
            return cls
        return loaded
    root_s = str(root)
    if root.is_dir() and root_s not in sys.path:
        sys.path.insert(0, root_s)
    mod = importlib.import_module(mod_name)
    if not cls_name:
        return mod
    cls = getattr(mod, cls_name, None)
    if cls is None:
        raise RuntimeError(f"nooa_agent_class_missing:{cls_name}")
    return cls


def _is_nooa_agent_type(cls: Any) -> bool:
    try:
        from nooa import Agent as NooaAgent
    except ImportError:
        return False
    return isinstance(cls, type) and issubclass(cls, NooaAgent)


def _build_llm(*, model: str, api_base: str | None, api_key: str | None) -> Any:
    overrides: dict[str, Any] = {"temperature": 0}
    base = (
        api_base or os.environ.get("OPENAI_BASE_URL") or os.environ.get("litellm_base_url")  # noqa: SIM112
    )
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if base:
        overrides["api_base"] = base
    if key:
        overrides["api_key"] = key
    if not key and not _is_http_loopback(base if isinstance(base, str) else None):
        raise RuntimeError("nooa_missing_credential")
    from nooa.unifiedllm import get_llm_client

    return get_llm_client(model or "openai/gpt-4.1-mini", **overrides)


def _load_trajectory():
    try:
        from nooa_plugin import trajectory as traj
    except ImportError:
        import importlib.util

        path = Path("/opt/nooa/nooa_plugin/trajectory.py")
        if not path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("nooa_plugin_trajectory", path)
        if spec is None or spec.loader is None:
            return None
        traj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(traj)
    return traj


def _tap_agent(agent: Any) -> Any:
    traj = _load_trajectory()
    if traj is None:
        return None
    return traj.attach_event_tap(agent)


def _finish_tap(tap: Any, agent: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    traj = _load_trajectory()
    if traj is None:
        return [], []
    dump_native_events = traj.dump_native_events
    to_ageval_trajectory_events = traj.to_ageval_trajectory_events
    if tap is not None and hasattr(tap, "finish"):
        native = tap.finish(agent)
    else:
        native = dump_native_events(agent)
    return native, to_ageval_trajectory_events(native)


def _to_result(
    raw: Any,
    *,
    agent_ref: str,
    model: str,
    llm_backed: bool,
    events: list[dict[str, Any]] | None = None,
    native_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = {
        "plugin": "nooa",
        "agent": agent_ref,
        "execution_location": "attempt-container",
        "llm_backed": llm_backed,
    }
    if hasattr(raw, "model_dump") and callable(raw.model_dump):
        dumped: Any = None
        try:
            dumped = raw.model_dump()
        except (TypeError, ValueError, AttributeError):
            dumped = None
        if isinstance(dumped, dict):
            raw = dumped
    if isinstance(raw, dict):
        if "ok" in raw or "text" in raw or "error" in raw:
            structured = raw.get("structured")
            if not isinstance(structured, dict):
                structured = {
                    k: v for k, v in raw.items() if k not in {"ok", "error", "text"}
                } or None
            text = str(raw.get("text") or "")
            if not text and structured is not None:
                text = json.dumps(structured, ensure_ascii=False)
            return {
                "model": model,
                "text": text,
                "structured": structured if isinstance(structured, dict) else None,
                "ok": bool(raw.get("ok", True)),
                "error": str(raw["error"]) if raw.get("error") else None,
                "events": events or [],
                "native_events": native_events or [],
                "metadata": meta,
            }
        text = json.dumps(raw, ensure_ascii=False)
        return {
            "model": model,
            "text": text,
            "structured": raw,
            "ok": True,
            "error": None,
            "events": events or [],
            "native_events": native_events or [],
            "metadata": meta,
        }
    text = str(raw) if raw is not None else ""
    structured = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            structured = parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "model": model,
        "text": text,
        "structured": structured,
        "ok": True,
        "error": None,
        "events": events or [],
        "native_events": native_events or [],
        "metadata": meta,
    }


async def _invoke(
    agent: Any,
    method_name: str,
    prompt: str,
    workdir: str,
) -> Any:
    method = getattr(agent, method_name, None)
    if method is None or not callable(method):
        raise RuntimeError(f"nooa_method_missing:{method_name}")
    try:
        out = method(prompt, workdir=workdir)
    except TypeError:
        out = method(prompt)
    if inspect.isawaitable(out):
        return await out
    return out


def _read_request() -> dict[str, Any]:
    raw = sys.argv[1] if len(sys.argv) > 1 else (sys.stdin.read() or "{}")
    req = json.loads(raw)
    if not isinstance(req, dict):
        raise TypeError("request_not_object")
    return req


def main() -> int:
    try:
        req = _read_request()
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"ok": False, "error": f"bad_request_json:{exc}", "model": "nooa", "text": ""}
            )
        )
        return 2
    except TypeError:
        print(json.dumps({"ok": False, "error": "request_not_object", "model": "nooa", "text": ""}))
        return 2

    agent_ref = str(req.get("agent") or "").strip()
    method_name = str(req.get("method") or "run").strip() or "run"
    prompt = str(req.get("prompt") or "")
    model = str(req.get("model") or os.environ.get("NOOA_MODEL") or "openai/gpt-4.1-mini")
    api_base = req.get("api_base") or req.get("base_url")
    api_base_s = str(api_base).strip() if isinstance(api_base, str) and api_base.strip() else None
    package_root = Path(str(req.get("package_root") or "/attempt/package")).expanduser()
    workdir = str(req.get("workdir") or "/attempt/workspace")

    if not agent_ref:
        print(
            json.dumps(
                {"ok": False, "error": "nooa_options_agent_required", "model": model, "text": ""}
            )
        )
        return 2

    if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1":
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "offline_forced",
                    "model": model,
                    "text": "",
                    "metadata": {
                        "plugin": "nooa",
                        "agent": agent_ref,
                        "execution_location": "attempt-container",
                    },
                }
            )
        )
        return 1

    try:
        cls = _load_agent_class(agent_ref, package_root)
        llm_backed = _is_nooa_agent_type(cls)
        if llm_backed:
            llm = _build_llm(model=model, api_base=api_base_s, api_key=None)
            agent = cls(llm=llm)
        else:
            agent = cls() if callable(cls) else cls
        tap = _tap_agent(agent)
        if llm_backed:
            raw = asyncio.run(_invoke(agent, method_name, prompt, workdir))
        else:
            method = getattr(agent, method_name, None)
            if method is None or not callable(method):
                raise RuntimeError(f"nooa_method_missing:{method_name}")
            try:
                raw = method(prompt, workdir=workdir)
            except TypeError:
                raw = method(prompt)
            if inspect.isawaitable(raw):
                raw = asyncio.run(raw)
        native, mapped = _finish_tap(tap, agent)
        out = _to_result(
            raw,
            agent_ref=agent_ref,
            model=model,
            llm_backed=llm_backed,
            events=mapped,
            native_events=native,
        )
        if tap is not None and hasattr(tap, "stats"):
            md = dict(out.get("metadata") or {})
            md["trajectory_tap"] = tap.stats
            out["metadata"] = md
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0 if out.get("ok") else 1
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "model": model,
                    "text": "",
                    "structured": None,
                    "ok": False,
                    "error": f"{type(exc).__name__}:{exc}",
                    "metadata": {
                        "plugin": "nooa",
                        "agent": agent_ref,
                        "execution_location": "attempt-container",
                    },
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
