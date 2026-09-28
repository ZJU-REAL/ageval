"""TTY-first CLI presentation. Pipes keep the JSON document."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ageval.cli.run_output import (
    dataset_label,
    dump_json,
    print_human,
    use_json_stdout,
)

_OMIT = frozenset(
    {
        "digest",
        "package_digest",
        "blob_digest",
        "digest_ref",
        "descriptor_digest",
        "config_fingerprint",
        "fingerprint",
        "resolved_references",
        "resolution",
        "media_type",
        "format",
        "schema",
        "job_overlay",
        "actors_summary",
        "plugins",
        "metrics",
        "task_refs",
        "note",
        "slots_summary",
        "path",
        "config_homogeneous",
        "extension_bindings",
        "provenance",
        "plugin_requires",
        "already_exists",
        "size",
        "binary_path",
        "acp_command",
        "engine_command",
        "binary_on_path",
        "bake_recipe_declared",
        "execution_mode",
        "integration_mode",
        "readiness",
        "engine_version",
        "acp_version",
        "kind",
        "ok",
        "campaign",
        "copied",
    }
)
_LABEL_W = 10


def emit(payload: Mapping[str, Any], *, err: bool = False, json_out: bool = False) -> None:
    """JSON on a pipe / ``--json``; short recap on a TTY."""
    import sys

    stream = sys.stderr if err else sys.stdout
    if use_json_stdout(force_json=json_out, stream=stream):
        dump_json(payload) if not err else _dump_json_stream(payload, stream)
        return
    print_human(humanize(payload, width=_tty_width(stream)), stream=stream)


def humanize(payload: Mapping[str, Any], *, width: int | None = None) -> str:
    """Plain recap. Dim / color is applied at print time."""
    if payload.get("ok") is False:
        return _error_block(payload)
    if "ready" in payload and "started" in payload:
        return _probe_block(payload)
    tasks = payload.get("tasks")
    if (
        isinstance(tasks, list)
        and "dataset_id" in payload
        and tasks
        and not isinstance(tasks[0], dict)
    ):
        return _tasks_block(payload)
    if "task_id" in payload and "environment" in payload and "dataset_id" in payload:
        return _lock_block(payload)
    if "executors" in payload and "acp_entries" in payload:
        return _executors_block(payload)
    if "plugins" in payload and isinstance(payload.get("plugins"), list):
        return _id_version_table(
            payload["plugins"], id_key="plugin_id", title="plugins", width=width
        )
    if "agents" in payload and isinstance(payload.get("agents"), list):
        return _id_version_table(payload["agents"], id_key="agent_id", title="agents", width=width)
    if payload.get("campaign"):
        return _campaign_block(payload)
    if payload.get("kind") == "snapshot-share" and payload.get("url"):
        lines = [_kv("url", str(payload["url"]))]
        suite_id = payload.get("suite_run_id")
        if suite_id:
            lines.append(_kv("suite", str(suite_id)))
        mode = payload.get("mode")
        if mode:
            lines.append(_kv("mode", str(mode)))
        run_id = payload.get("run_id")
        if run_id:
            lines.append(_kv("run", str(run_id)))
        return "\n".join(lines) + "\n"
    if payload.get("revoked") is True and payload.get("token"):
        return _kv("revoked", str(payload["token"])) + "\n"
    if payload.get("suite_run_id") and "pass_rate" in payload:
        return _suite_upload_block(payload)
    if payload.get("github_user") is not None or payload.get("credentials_path"):
        return _login_block(payload)
    if payload.get("uninstalled"):
        return _kv("removed", str(payload["uninstalled"])) + "\n"
    if payload.get("plugin_id") and payload.get("ok"):
        return _install_block(payload, id_key="plugin_id")
    if payload.get("agent_id") and payload.get("ok") and "digest" in payload:
        return _install_block(payload, id_key="agent_id")
    if payload.get("ref") and payload.get("dataset_id"):
        return _publish_block(payload)
    if payload.get("run_id") and payload.get("ok") and "dataset_id" in payload:
        return _attempt_upload_block(payload)
    if "items" in payload and isinstance(payload.get("items"), list):
        return _items_block(payload)
    if payload.get("progress") or (
        payload.get("ok") and payload.get("run_id") and "status" in payload
    ):
        return _status_block(payload)
    if payload.get("export_path") is not None:
        return _kv("export", str(payload.get("export_path") or "")) + "\n"
    if payload.get("cancel_requested") is not None or payload.get("status") == "cancelled":
        return _cancel_block(payload)
    return _generic_block(payload)


def _dump_json_stream(payload: Mapping[str, Any], stream: Any) -> None:
    import json

    stream.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    stream.flush()


def _tty_width(stream: Any) -> int | None:
    from rich.console import Console

    console = Console(file=stream, highlight=False)
    if not console.is_terminal:
        return None
    return max(1, int(console.width))


def _ellipsis(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _kv(label: str, value: str) -> str:
    return f"{label:<{_LABEL_W}}{value}"


def _ready(flag: object) -> str:
    return "ready" if flag else "missing"


def _probe_block(payload: Mapping[str, Any]) -> str:
    lines = [_kv("probe", str(payload.get("task_id") or ""))]
    env = payload.get("environment")
    if env:
        lines.append(_kv("env", str(env)))
    lines.append(_kv("ready", "yes" if payload.get("ready") else "no"))
    err = payload.get("error")
    if err:
        lines.append(_kv("error", str(err)))
    return "\n".join(lines) + "\n"


def _error_block(payload: Mapping[str, Any]) -> str:
    code = str(payload.get("error") or payload.get("error_code") or "error")
    msg = str(payload.get("message") or payload.get("hint") or "")
    line = _kv("error", code if not msg else f"{code}  {msg}")
    return line + "\n"


def _tasks_block(payload: Mapping[str, Any]) -> str:
    label = dataset_label(str(payload.get("dataset_id") or ""), str(payload.get("version") or ""))
    ids = [str(t) for t in payload.get("tasks") or [] if str(t)]
    lines = [label] if label else []
    width = max((len(i) for i in ids), default=8)
    lines.extend(f"  {i:<{width}}" for i in ids)
    n = payload.get("count")
    if isinstance(n, int) and not isinstance(n, bool):
        lines.append(f"{n} task" if n == 1 else f"{n} tasks")
    return "\n".join(lines) + "\n"


def _lock_block(payload: Mapping[str, Any]) -> str:
    head = dataset_label(
        str(payload.get("dataset_id") or ""),
        str(payload.get("dataset_version") or ""),
    )
    task = str(payload.get("task_id") or "")
    lines = [_kv("lock", f"{head}  {task}".strip())]
    env = str(payload.get("environment") or "")
    if env:
        lines.append(_kv("env", env))
    profile = payload.get("profile")
    if profile:
        lines.append(_kv("profile", str(profile)))
    overlay = payload.get("job_overlay")
    if isinstance(overlay, Mapping):
        lines.extend(_binding_lines(overlay))
    return "\n".join(lines) + "\n"


def _binding_lines(overlay: Mapping[str, Any]) -> list[str]:
    profiles = overlay.get("agent_profiles")
    if not isinstance(profiles, Mapping):
        profiles = overlay.get("bindings")
    if not isinstance(profiles, Mapping):
        return []
    rows: list[list[str]] = []
    for role, spec in profiles.items():
        if not isinstance(spec, Mapping):
            continue
        executor = str(spec.get("executor") or "")
        model = str(spec.get("model") or "")
        raw_opts = spec.get("options")
        opts: Mapping[str, Any] = raw_opts if isinstance(raw_opts, Mapping) else {}
        entry = str(opts.get("entry") or spec.get("entry") or "")
        cells = [str(role), executor]
        if entry:
            cells.append(entry)
        if model:
            cells.append(model)
        rows.append(cells)
    if not rows:
        return []
    return ["  " + line for line in _align_cells(rows)]


def _executors_block(payload: Mapping[str, Any]) -> str:
    lines = ["executors"]
    exec_rows: list[list[str]] = []
    for row in payload.get("executors") or []:
        if not isinstance(row, Mapping):
            continue
        exec_rows.append([str(row.get("kind") or ""), _ready(row.get("host_ready"))])
    if exec_rows:
        lines.extend("  " + line for line in _align_cells(exec_rows))
    entries = [r for r in (payload.get("acp_entries") or []) if isinstance(r, Mapping)]
    if entries:
        lines.append("─" * 40)
        lines.append("acp")
        acp_rows = [[str(r.get("entry_id") or ""), _ready(r.get("host_ready"))] for r in entries]
        lines.extend("  " + line for line in _align_cells(acp_rows))
    return "\n".join(lines) + "\n"


def _id_version_table(
    rows: Sequence[Any],
    *,
    id_key: str,
    title: str,
    width: int | None = None,
) -> str:
    prepared: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ident = str(row.get(id_key) or row.get("id") or "")
        ver = str(row.get("version") or "")
        extra = " ".join(
            str(row.get("description") or row.get("label") or row.get("visibility") or "").split()
        )
        prepared.append((ident, ver, extra))
    if not prepared:
        return f"{title}\n  (none)\n"
    id_w = max(len(p[0]) for p in prepared)
    ver_w = max(len(p[1]) for p in prepared)
    extra_budget: int | None = None
    if width is not None:
        extra_budget = width - 2 - id_w - 2 - ver_w - 2
    cells: list[list[str]] = []
    for ident, ver, extra in prepared:
        line = [ident, ver]
        if extra and (extra_budget is None or extra_budget > 0):
            line.append(extra if extra_budget is None else _ellipsis(extra, extra_budget))
        cells.append(line)
    out = [title, *("  " + line for line in _align_cells(cells))]
    return "\n".join(out) + "\n"


def _install_block(payload: Mapping[str, Any], *, id_key: str) -> str:
    ident = str(payload.get(id_key) or "")
    ver = str(payload.get("version") or "")
    ref = str(payload.get("ref") or (f"{ident}@{ver}" if ver else ident))
    return _kv("installed", ref) + "\n"


def _publish_block(payload: Mapping[str, Any]) -> str:
    ref = str(
        payload.get("ref")
        or dataset_label(
            str(payload.get("dataset_id") or ""),
            str(payload.get("version") or ""),
        )
    )
    vis = str(payload.get("visibility") or "")
    verb = "published"
    if payload.get("is_draft") or payload.get("slot") == "draft":
        verb = "draft"
    elif payload.get("from_draft"):
        verb = "released"
    value = f"{ref}  {vis}".strip()
    lines = [_kv(verb, value)]
    if payload.get("replaced"):
        lines.append(_kv("replaced", "yes"))
    org = payload.get("org_id")
    if org:
        lines.append(_kv("org", str(org)))
    return "\n".join(lines) + "\n"


def _suite_upload_block(payload: Mapping[str, Any]) -> str:
    head = dataset_label(
        str(payload.get("dataset_id") or ""),
        str(payload.get("dataset_version") or ""),
    )
    sid = str(payload.get("suite_run_id") or "")
    vis = str(payload.get("visibility") or "")
    bits = [b for b in (head, f"suite {sid}" if sid else "", vis) if b]
    lines = [_kv("uploaded", "  ".join(bits))]
    n_att = payload.get("attempts_total")
    if isinstance(n_att, int) and not isinstance(n_att, bool) and n_att:
        uploaded = payload.get("attempts_uploaded")
        extra = f"{n_att}"
        if isinstance(uploaded, int) and not isinstance(uploaded, bool):
            extra = f"{uploaded}/{n_att}"
        lines.append(_kv("attempts", extra))
    rate = payload.get("pass_rate")
    if isinstance(rate, int | float) and not isinstance(rate, bool):
        lines.append(_kv("pass_rate", f"{float(rate):.0%}"))
    return "\n".join(lines) + "\n"


def _attempt_upload_block(payload: Mapping[str, Any]) -> str:
    rid = str(payload.get("run_id") or "")
    vis = str(payload.get("visibility") or "")
    verb = "exists" if payload.get("already_exists") else "uploaded"
    return _kv(verb, f"{rid}  {vis}".strip()) + "\n"


def _login_block(payload: Mapping[str, Any]) -> str:
    user = str(payload.get("github_user") or "user")
    lines = [_kv("logged in", user)]
    url = payload.get("registry_url")
    if url:
        lines.append(_kv("registry", str(url)))
    return "\n".join(lines) + "\n"


def _campaign_block(payload: Mapping[str, Any]) -> str:
    head = str(payload.get("dataset_id") or "campaign")
    lines = [f"campaign  {head}"]
    rows: list[list[str]] = []
    for trial in payload.get("trials") or []:
        if not isinstance(trial, Mapping):
            continue
        tid = str(trial.get("task_id") or "")
        status = str(trial.get("status") or "").upper()
        rows.append([tid, status])
    if rows:
        lines.extend("  " + line for line in _align_cells(rows))
    n_pass = sum(1 for r in rows if r[-1] == "PASS")
    lines.append(f"{n_pass}/{len(rows)} PASS" if rows else "0/0 PASS")
    path = payload.get("summary_path")
    if path:
        lines.append("─" * 40)
        lines.append(_kv("summary", str(path)))
    return "\n".join(lines) + "\n"


def _items_block(payload: Mapping[str, Any]) -> str:
    items = [r for r in (payload.get("items") or []) if isinstance(r, Mapping)]
    title = "packages"
    if payload.get("cache_root"):
        title = "cache"
    elif items and "job_id" in items[0]:
        title = "jobs"
    elif items and "run_id" in items[0]:
        title = "results"
    elif items and "suite_run_id" in items[0] and "dataset_id" not in items[0]:
        title = "suites"
    elif items and "name" in items[0] and "dataset_id" not in items[0]:
        title = "orgs"
    cells: list[list[str]] = []
    for row in items:
        ident = str(
            row.get("job_id")
            or row.get("dataset_id")
            or row.get("run_id")
            or row.get("suite_run_id")
            or row.get("name")
            or row.get("id")
            or row.get("path")
            or ""
        )
        ver = str(row.get("version") or row.get("role") or "")
        vis = str(row.get("visibility") or row.get("status") or "")
        col = [ident]
        if ver:
            col.append(ver)
        if vis:
            col.append(vis)
        cells.append(col)
    if not cells:
        return f"{title}\n  (none)\n"
    lines = [title, *("  " + line for line in _align_cells(cells))]
    n = payload.get("count")
    if isinstance(n, int) and not isinstance(n, bool):
        lines.append(f"{n} listed")
    return "\n".join(lines) + "\n"


def _status_block(payload: Mapping[str, Any]) -> str:
    rid = str(payload.get("run_id") or "")
    status = str(payload.get("status") or "")
    lines = [_kv("status", f"{rid}  {status}".strip())]
    prog = payload.get("progress")
    if isinstance(prog, Mapping):
        done = prog.get("done")
        total = prog.get("total")
        if done is not None and total is not None:
            lines.append(_kv("progress", f"{done}/{total}"))
    if payload.get("cancel_requested"):
        lines.append(_kv("cancel", "requested"))
    return "\n".join(lines) + "\n"


def _cancel_block(payload: Mapping[str, Any]) -> str:
    rid = str(payload.get("run_id") or "")
    kind = str(payload.get("kind") or "")
    return _kv("cancelled", f"{kind}  {rid}".strip()) + "\n"


def _generic_block(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key, value in payload.items():
        if key in _OMIT or value is None or value is True:
            continue
        if value is False:
            continue
        if isinstance(value, Mapping):
            continue
        if isinstance(value, list):
            if value and all(isinstance(x, Mapping) for x in value):
                ident_key = next(
                    (k for k in ("id", "name", "task_id", "run_id") if k in value[0]),
                    None,
                )
                if ident_key:
                    cells = []
                    for row in value:
                        cells.append(
                            [
                                str(row.get(ident_key) or ""),
                                str(row.get("status") or row.get("version") or ""),
                            ]
                        )
                    lines.extend("  " + line for line in _align_cells(cells) if line.strip())
            elif value and all(not isinstance(x, (dict, list)) for x in value):
                lines.append(_kv(str(key), " ".join(str(x) for x in value)))
            continue
        lines.append(_kv(str(key), str(value)))
    if not lines:
        return "ok\n"
    return "\n".join(lines) + "\n"


def _align_cells(rows: Sequence[Sequence[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    cols = list(range(width))
    max_w = [0] * width
    norm = []
    for row in rows:
        cells = [str(c) for c in row] + [""] * (width - len(row))
        norm.append(cells)
        for i, cell in enumerate(cells):
            max_w[i] = max(max_w[i], len(cell))
    lines = []
    for cells in norm:
        parts = [f"{cells[i]:<{max_w[i]}}" for i in cols if max_w[i] or cells[i]]
        lines.append(
            "  ".join(p.rstrip() if i == len(parts) - 1 else p for i, p in enumerate(parts))
        )
    return lines
