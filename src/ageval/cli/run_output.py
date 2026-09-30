"""Human recap and live progress for ``ageval run`` (TTY). Machine JSON unchanged."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

_STATUS_STYLE = {"PASS": "green", "FAIL": "red", "ERROR": "yellow"}
_STATUS_RE = re.compile(r"\b(PASS|FAIL|ERROR)\b")
_RECAP_RULE = "─" * 40


def _clock_text(seconds: float | None) -> str:
    """Progressive live-bar clock: seconds, then minutes, then hours."""
    if seconds is None:
        return "-"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, min2 = divmod(minutes, 60)
    return f"{hours}h {min2:02d}m {sec:02d}s"


class _SuiteElapsedColumn(ProgressColumn):
    """Current unit's elapsed time, with the suite total in secondary color."""

    def __init__(self, state: RunProgress) -> None:
        super().__init__()
        self._state = state

    def render(self, task: Task) -> Text:
        current = self._state.current_unit_elapsed_seconds()
        total = self._state.suite_elapsed_seconds()
        segments: list[tuple[str, str]] = [(_clock_text(current), "progress.elapsed")]
        if total is not None:
            segments.append((f" (total {_clock_text(total)})", "dim"))
        return Text.assemble(*segments)


def use_json_stdout(*, force_json: bool = False, stream: TextIO | None = None) -> bool:
    """True when stdout should be the full result document."""
    if force_json:
        return True
    out = sys.stdout if stream is None else stream
    isatty = getattr(out, "isatty", None)
    return not callable(isatty) or not isatty()


def use_progress_bar(*, stream: TextIO | None = None) -> bool:
    """True when stderr can host the live spinner / N-of-M line."""
    err = sys.stderr if stream is None else stream
    isatty = getattr(err, "isatty", None)
    return callable(isatty) and bool(isatty())


def dataset_label(dataset_id: str, version: str | None = None) -> str:
    ds = str(dataset_id or "").strip()
    ver = str(version or "").strip()
    return f"{ds}@{ver}" if ds and ver else ds


def recap_view_arg(dataset_root: Path | str, summary: Mapping[str, Any]) -> str:
    """Short ``id@version`` when the run lived in the verified cache; else a path."""
    label = dataset_label(
        str(summary.get("dataset_id") or ""),
        str(summary.get("dataset_version") or "") or None,
    )
    parts = Path(dataset_root).parts
    if label and any(str(part).startswith("sha256_") for part in parts):
        return label
    return display_path(dataset_root)


def display_path(path: Path | str) -> str:
    """Prefer a cwd-relative path for recap ``next`` / ``summary`` lines."""
    raw = Path(path)
    try:
        rel = raw.expanduser().resolve().relative_to(Path.cwd().resolve())
        text = str(rel)
        return "." if text == "." else text
    except (OSError, ValueError):
        return str(raw)


def format_duration_ms(ms: float | None) -> str:
    """Short wall label: ``12ms``, ``8.1s``, ``1m 04s``."""
    if ms is None or isinstance(ms, bool) or not isinstance(ms, int | float):
        return ""
    if ms < 0:
        ms = 0.0
    if ms < 1000:
        return f"{int(round(ms))}ms"
    total_s = ms / 1000.0
    if total_s < 60:
        return f"{total_s:.1f}s"
    minutes = int(total_s // 60)
    seconds = int(round(total_s - minutes * 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}m {seconds:02d}s" if seconds else f"{minutes}m"


def dump_json(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def print_human(text: str, *, stream: TextIO | None = None) -> None:
    out = sys.stdout if stream is None else stream
    body = text if text.endswith("\n") else f"{text}\n"
    console = Console(file=out, highlight=False, soft_wrap=True)
    if not console.is_terminal or console.no_color:
        out.write(body)
        out.flush()
        return
    for line in body.splitlines():
        console.print(_recap_markup(line))


def format_suite_recap(
    summary: Mapping[str, Any],
    *,
    dataset_root: Path | str,
) -> str:
    """End-of-run footer only. Unit rows already went to stderr during the run."""
    sid = str(summary.get("suite_run_id") or "")
    raw_counts = summary.get("counts")
    counts: Mapping[str, Any] = raw_counts if isinstance(raw_counts, Mapping) else {}
    n_pass = int(counts.get("pass") or 0)
    n_fail = int(counts.get("fail") or 0)
    n_error = int(counts.get("error") or 0)
    n_skip = int(counts.get("skipped") or 0)
    total = n_pass + n_fail + n_error + n_skip
    if total <= 0:
        task_ids = summary.get("task_ids")
        total = len(task_ids) if isinstance(task_ids, list) else 0
    footer_bits = [f"{n_pass}/{total} PASS"]
    if n_fail:
        footer_bits.append(f"{n_fail} FAIL")
    if n_error:
        footer_bits.append(f"{n_error} ERROR")
    if n_skip:
        footer_bits.append(f"{n_skip} skipped")
    if summary.get("cancelled"):
        footer_bits.append("cancelled")
    n_attempts = summary.get("n_attempts")
    if isinstance(n_attempts, int) and not isinstance(n_attempts, bool) and n_attempts > 1:
        footer_bits.append(f"k={n_attempts}")
    footer_bits.append(f"exit={int(summary.get('exit_code', 2))}")
    lines = [_RECAP_RULE, "   ".join(footer_bits)]
    summary_path = summary.get("summary_path")
    ds_arg = recap_view_arg(dataset_root, summary)
    if summary_path:
        lines.append(f"summary  {display_path(str(summary_path))}")
    lines.append(f"next     ageval view {ds_arg}")
    if sid:
        lines.append(f"         ageval results upload-suite {ds_arg} --suite-run {sid}")
    return "\n".join(lines) + "\n"


def format_attempt_recap(
    result: Mapping[str, Any],
    *,
    task_id: str,
    dataset_root: Path | str,
    duration: str = "",
    dataset_id: str = "",
    dataset_version: str = "",
) -> str:
    status = str(result.get("status") or "ERROR").upper()
    head = f"task {task_id}  {status}"
    if duration:
        head = f"{head}  {duration}"
    lines = [head]
    error = result.get("error")
    if isinstance(error, Mapping) and error.get("phase"):
        lines.append(f"error    phase={error['phase']}")
    logs = result.get("logs") or result.get("evidence_path")
    if logs:
        lines.append(f"logs     {display_path(str(logs))}")
    view_arg = recap_view_arg(
        dataset_root,
        {"dataset_id": dataset_id, "dataset_version": dataset_version},
    )
    lines.append(f"next     ageval view {view_arg}")
    return "\n".join(lines) + "\n"


class RunProgress:
    """Stderr progress for a suite: aligned status lines, plus a TTY bar."""

    def __init__(
        self,
        *,
        suite_run_id: str,
        dataset_label: str,
        stderr: TextIO | None = None,
        use_bar: bool | None = None,
        use_color: bool | None = None,
        monotonic: Any = time.monotonic,
        task_ids: Sequence[str] | None = None,
        n_attempts: int = 1,
    ) -> None:
        self.suite_run_id = suite_run_id
        self.dataset_label = dataset_label
        self._stderr = sys.stderr if stderr is None else stderr
        self._now = monotonic
        self._use_bar = use_progress_bar(stream=self._stderr) if use_bar is None else use_bar
        if use_color is None:
            isatty = getattr(self._stderr, "isatty", None)
            self._use_color = callable(isatty) and bool(isatty()) and not os.environ.get("NO_COLOR")
        else:
            self._use_color = use_color
        self._started: dict[tuple[str, int], float] = {}
        self._elapsed: dict[tuple[str, int], str] = {}
        self._running: dict[tuple[str, int], str | None] = {}
        self._suite_started: float | None = None
        names = [str(t) for t in (task_ids or ()) if str(t)]
        self._name_width = max((len(n) for n in names), default=8)
        self._show_attempt = (
            isinstance(n_attempts, int) and not isinstance(n_attempts, bool) and n_attempts > 1
        )
        self._progress: Progress | None = None
        self._bar_task: TaskID | None = None
        self._console = Console(
            file=self._stderr,
            highlight=False,
            soft_wrap=True,
            no_color=not self._use_color,
        )

    def elapsed_labels(self) -> dict[tuple[str, int], str]:
        return dict(self._elapsed)

    def current_unit_elapsed_seconds(self) -> float | None:
        """Wall seconds since the first still-running unit started."""
        for key in self._running:
            started = self._started.get(key)
            if started is not None:
                return max(0.0, float(self._now()) - started)
        return None

    def suite_elapsed_seconds(self) -> float | None:
        """Wall seconds since the suite bar started."""
        if self._suite_started is None:
            return None
        return max(0.0, float(self._now()) - self._suite_started)

    def close(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._bar_task = None

    def handle(self, ev: dict[str, Any]) -> None:
        kind = str(ev.get("type") or "")
        if kind == "suite_start":
            self._on_start(ev)
        elif kind == "unit_start":
            self._on_unit_start(ev)
        elif kind == "unit_phase":
            self._on_unit_phase(ev)
        elif kind == "upstream_stall":
            self._on_upstream_stall(ev)
        elif kind == "unit_done":
            self._on_unit_done(ev)
        elif kind == "suite_complete":
            self._on_complete(ev)
        elif kind == "suite_cancelled":
            self._on_cancelled(ev)

    def _on_start(self, ev: Mapping[str, Any]) -> None:
        total = int(ev.get("total") or 0)
        done = int(ev.get("done") or 0)
        header = f"suite {self.suite_run_id}  {self.dataset_label}".rstrip()
        if not self._use_bar:
            todo = ev.get("todo")
            extra = f"  todo={todo} total={total}" if todo is not None else f"  total={total}"
            header = f"{header}{extra}  cancel: ageval cancel {self.suite_run_id}"
        self._emit(header)
        if self._use_bar:
            self._suite_started = float(self._now())
        if self._use_bar and total > 0:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                MofNCompleteColumn(),
                _SuiteElapsedColumn(self),
                console=self._console,
                transient=True,
            )
            progress.start()
            self._progress = progress
            self._bar_task = progress.add_task("starting", total=total, completed=done)

    def _on_unit_start(self, ev: Mapping[str, Any]) -> None:
        key = _unit_key(ev)
        self._started[key] = float(self._now())
        self._running[key] = None
        tid = key[0]
        self._name_width = max(self._name_width, len(tid))
        if key[1] != 0:
            self._show_attempt = True
        if self._use_bar:
            self._refresh_bar(int(ev.get("done") or 0), int(ev.get("total") or 0))
            return
        self._emit(f"start  {_plain_unit_label(key, show_attempt=self._show_attempt)}")

    def _on_unit_phase(self, ev: Mapping[str, Any]) -> None:
        key = _unit_key(ev)
        phase = str(ev.get("phase") or "")
        self._running[key] = phase or None
        if self._progress is not None and self._bar_task is not None:
            self._progress.update(self._bar_task, description=self._bar_description())

    def _on_upstream_stall(self, ev: Mapping[str, Any]) -> None:
        key = _unit_key(ev)
        outcome = str(ev.get("outcome") or "")
        phase = str(ev.get("phase") or "")
        if outcome in {"started", "wait"}:
            self._running[key] = "upstream_stall"
        else:
            self._running[key] = phase or None
        if self._use_bar:
            if self._progress is not None and self._bar_task is not None:
                self._progress.update(self._bar_task, description=self._bar_description())
            return
        self._emit(format_upstream_stall_line(ev))

    def _on_unit_done(self, ev: Mapping[str, Any]) -> None:
        key = _unit_key(ev)
        self._running.pop(key, None)
        label = self._duration_for(key, ev)
        if label:
            self._elapsed[key] = label
        self._name_width = max(self._name_width, len(key[0]))
        if key[1] != 0:
            self._show_attempt = True
        status = str(ev.get("status") or "").upper() or "ERROR"
        line = _format_unit_line(
            key,
            status,
            label,
            name_width=self._name_width,
            show_attempt=self._show_attempt,
        )
        self._emit(line)
        if self._use_bar:
            self._refresh_bar(int(ev.get("done") or 0), int(ev.get("total") or 0))

    def _on_complete(self, ev: Mapping[str, Any]) -> None:
        if self._use_bar:
            return
        done = ev.get("done")
        total = ev.get("total")
        self._emit(f"suite complete  exit={ev.get('exit_code')}  done={done}/{total}")

    def _on_cancelled(self, ev: Mapping[str, Any]) -> None:
        if self._use_bar:
            return
        done = ev.get("done")
        total = ev.get("total")
        skipped = ev.get("cancelled_units")
        self._emit(f"suite cancelled  done={done}/{total}  skipped={skipped}")

    def _duration_for(self, key: tuple[str, int], ev: Mapping[str, Any]) -> str:
        raw = ev.get("duration")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return format_duration_ms(float(raw))
        started = self._started.get(key)
        if started is None:
            return ""
        return format_duration_ms((float(self._now()) - started) * 1000.0)

    def _refresh_bar(self, done: int, total: int) -> None:
        if self._progress is None or self._bar_task is None:
            return
        if self._running:
            desc = self._bar_description()
        else:
            desc = "done" if done >= total and total else "waiting"
        self._progress.update(self._bar_task, completed=done, total=max(total, 1), description=desc)

    def _bar_description(self) -> str:
        """First running unit, phase-annotated; ``+N`` when units interleave."""
        running = list(self._running.items())
        key, phase = running[0]
        label = f"{key[0]} ({phase})" if phase else key[0]
        if len(running) > 1:
            label = f"{label} +{len(running) - 1}"
        return escape(label)

    def _emit(self, line: str) -> None:
        if self._progress is not None:
            self._progress.console.print(_status_markup(line) if self._use_color else line)
            return
        if self._use_color:
            self._console.print(_status_markup(line))
            return
        self._stderr.write(line + "\n")
        self._stderr.flush()


class AttemptSpinner:
    """Transient stderr spinner for one single-task Attempt: name + elapsed.

    Same TTY bar as the suite runner (spinner, name, 1/1, elapsed); inert when
    stderr is not a TTY so piped/CI output stays unchanged.
    """

    def __init__(
        self,
        *,
        task_id: str,
        stderr: TextIO | None = None,
        use_bar: bool | None = None,
        use_color: bool | None = None,
    ) -> None:
        self._stderr = sys.stderr if stderr is None else stderr
        self._use_bar = use_progress_bar(stream=self._stderr) if use_bar is None else use_bar
        if use_color is None:
            isatty = getattr(self._stderr, "isatty", None)
            self._use_color = callable(isatty) and bool(isatty()) and not os.environ.get("NO_COLOR")
        else:
            self._use_color = use_color
        self._task_id = task_id
        self._progress: Progress | None = None
        self._bar_task: TaskID | None = None
        self._console = Console(
            file=self._stderr,
            highlight=False,
            soft_wrap=True,
            no_color=not self._use_color,
        )

    def __enter__(self) -> AttemptSpinner:
        if not self._use_bar:
            return self
        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        )
        progress.start()
        self._progress = progress
        self._bar_task = progress.add_task(self._task_id, total=1)
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def phase(self, event: str, name: str) -> None:
        """Live label from the attempt observer: ``task (phase)`` on started.

        Parentheses, not brackets: rich reads task descriptions as console
        markup and would strip ``[phase]`` from the rendered line.
        """
        if self._progress is None or self._bar_task is None or event != "started" or not name:
            return
        self._progress.update(
            self._bar_task, description=f"{escape(self._task_id)} ({escape(name)})"
        )

    def stall(self, ev: Mapping[str, Any]) -> None:
        """One upstream-stall progress event. The bar reuses ``phase``; a pipe prints fields."""
        if str(ev.get("type") or "") != "upstream_stall":
            return
        outcome = str(ev.get("outcome") or "")
        if self._use_bar:
            if self._progress is None or self._bar_task is None:
                return
            name = (
                "upstream_stall" if outcome in {"started", "wait"} else str(ev.get("phase") or "")
            )
            if name:
                self._progress.update(
                    self._bar_task,
                    description=f"{escape(self._task_id)} ({escape(name)})",
                )
            return
        self._stderr.write(format_upstream_stall_line(ev) + "\n")
        self._stderr.flush()

    def close(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._bar_task = None


def format_upstream_stall_line(ev: Mapping[str, Any]) -> str:
    """Field line for a non-TTY stall event. Not a sentence."""
    task_id = str(ev.get("task_id") or "")
    state = str(ev.get("state") or "upstream_stall")
    outcome = str(ev.get("outcome") or "")
    nxt = int(ev.get("seconds_until_next") or 0)
    remaining = int(ev.get("remaining_budget") or 0)
    return (
        f"upstream_stall task={task_id} state={state} "
        f"next={nxt} remaining={remaining} outcome={outcome}"
    )


def _unit_key(ev: Mapping[str, Any]) -> tuple[str, int]:
    tid = str(ev.get("task_id") or "")
    idx = ev.get("attempt_index")
    if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
        idx = 0
    return tid, idx


def _plain_unit_label(key: tuple[str, int], *, show_attempt: bool) -> str:
    if show_attempt:
        return f"{key[0]}  #{key[1]}"
    return key[0]


def _format_unit_line(
    key: tuple[str, int],
    status: str,
    duration: str,
    *,
    name_width: int,
    show_attempt: bool,
) -> str:
    name = f"{key[0]:<{name_width}}"
    if show_attempt:
        name = f"{name}  #{key[1]}"
    if duration:
        return f"  {name}  {status:>5}  {duration}"
    return f"  {name}  {status:>5}"


def _status_markup(line: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        style = _STATUS_STYLE.get(token)
        return f"[{style}]{token}[/]" if style else token

    return _STATUS_RE.sub(repl, line)


def _recap_markup(line: str) -> str:
    """Status color plus dim on secondary columns and kv values."""
    if line == _RECAP_RULE or (line and set(line) <= {"─"}):
        return f"[dim]{line}[/]"
    if line.startswith("         ") and line.strip():
        return f"         [dim]{line[9:]}[/]"
    if re.match(r"^\d", line):
        return _status_markup(line)
    kv = re.match(r"^(\S+)(\s{2,})(.+)$", line)
    if kv and not line.startswith(" "):
        return f"{kv.group(1)}{kv.group(2)}[dim]{_status_markup(kv.group(3))}[/]"
    indented = re.match(r"^(  \S+)(\s{2,})(.+)$", line)
    if indented:
        rest = indented.group(3)
        dim_rest = f"[dim]{rest}[/]"
        dim_rest = _STATUS_RE.sub(
            lambda m: f"[/dim][{_STATUS_STYLE.get(m.group(1), 'dim')}]{m.group(1)}[/][dim]",
            dim_rest,
        )
        return f"{indented.group(1)}{indented.group(2)}{dim_rest}"
    return _status_markup(line)
