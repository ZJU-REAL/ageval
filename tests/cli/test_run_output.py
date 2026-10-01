"""TTY recap and plain progress for ``ageval run`` (no JSON blob)."""

from __future__ import annotations

import io
from pathlib import Path

from rich.progress import TextColumn

from ageval.cli.run_output import (
    AttemptSpinner,
    RunProgress,
    _SuiteElapsedColumn,
    dataset_label,
    format_attempt_recap,
    format_duration_ms,
    format_suite_recap,
    use_json_stdout,
)


def test_use_json_stdout_force_and_pipe() -> None:
    assert use_json_stdout(force_json=True, stream=io.StringIO()) is True
    assert use_json_stdout(force_json=False, stream=io.StringIO()) is True


def test_dataset_label_joins_version() -> None:
    assert dataset_label("official/demo", "0.1.0") == "official/demo@0.1.0"
    assert dataset_label("official/demo", "") == "official/demo"


def test_format_duration_ms_seconds() -> None:
    assert format_duration_ms(12) == "12ms"
    assert format_duration_ms(8100) == "8.1s"
    assert format_duration_ms(12_400) == "12.4s"


def test_suite_recap_omits_json_payload(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}\n", encoding="utf-8")
    text = format_suite_recap(
        {
            "suite_run_id": "863b8ee9",
            "dataset_id": "official/demo",
            "dataset_version": "0.1.0",
            "n_attempts": 1,
            "exit_code": 0,
            "summary_path": str(summary_path),
            "counts": {"pass": 2, "fail": 0, "error": 0, "skipped": 0},
            "task_ids": ["tau2-dialog-min", "terminal-jsonl-agg"],
            "tasks": [
                {"task_id": "tau2-dialog-min", "status": "PASS", "attempt_index": 0},
                {"task_id": "terminal-jsonl-agg", "status": "PASS", "attempt_index": 0},
            ],
            "actors_summary": [{"profile_id": "solver", "model": "secret-looking"}],
        },
        dataset_root=tmp_path,
    )
    first, counts, *_rest = text.splitlines()
    assert first and set(first) <= {"─"}
    assert counts == "2/2 PASS   exit=0"
    assert "tau2-dialog-min" not in text
    assert "terminal-jsonl-agg" not in text
    assert "suite 863b8ee9" not in text
    assert "summary  " in text
    assert "ageval view " in text
    assert "ageval results upload-suite " in text
    assert "sha256_" not in text.split("ageval view ", 1)[-1].splitlines()[0]
    assert "--suite-run 863b8ee9" in text
    assert "actors_summary" not in text
    assert "secret-looking" not in text
    assert "{" not in text


def test_suite_recap_k_and_fail() -> None:
    text = format_suite_recap(
        {
            "suite_run_id": "abcd1234",
            "dataset_id": "test/suite-min",
            "dataset_version": "0.1.0",
            "n_attempts": 2,
            "exit_code": 1,
            "counts": {"pass": 0, "fail": 1, "error": 0, "skipped": 0},
            "task_ids": ["alpha"],
            "attempts": [
                {"task_id": "alpha", "attempt_index": 0, "status": "PASS"},
                {"task_id": "alpha", "attempt_index": 1, "status": "FAIL"},
            ],
        },
        dataset_root=".",
    )
    assert "alpha" not in text
    assert "FAIL" in text
    assert "k=2" in text
    first, counts, *_rest = text.splitlines()
    assert first and set(first) <= {"─"}
    assert counts == "0/1 PASS   1 FAIL   k=2   exit=1"


def test_attempt_recap_has_logs_and_next() -> None:
    text = format_attempt_recap(
        {
            "status": "PASS",
            "logs": "runs/abc",
            "evidence_path": "runs/abc",
        },
        task_id="alpha",
        dataset_root="examples/core",
        duration="1.2s",
    )
    assert text.startswith("task alpha  PASS  1.2s\n")
    assert "logs     " in text
    assert "ageval view " in text
    assert "{" not in text


def test_plain_progress_aligns_done_line() -> None:
    buf = io.StringIO()
    clock = iter([0.0, 1.25, 1.25])
    progress = RunProgress(
        suite_run_id="863b8ee9",
        dataset_label="official/demo@0.1.0",
        stderr=buf,
        use_bar=False,
        use_color=False,
        monotonic=lambda: next(clock),
    )
    progress.handle({"type": "suite_start", "todo": 1, "total": 1, "done": 0})
    progress.handle(
        {
            "type": "unit_start",
            "task_id": "tau2-dialog-min",
            "attempt_index": 0,
            "done": 0,
            "total": 1,
        }
    )
    progress.handle(
        {
            "type": "unit_done",
            "task_id": "tau2-dialog-min",
            "attempt_index": 0,
            "status": "PASS",
            "done": 1,
            "total": 1,
        }
    )
    progress.close()
    text = buf.getvalue()
    assert "suite 863b8ee9  official/demo@0.1.0" in text
    assert "cancel: ageval cancel 863b8ee9" in text
    assert "start  tau2-dialog-min" in text
    assert "PASS" in text
    assert "1.2s" in text
    assert progress.elapsed_labels()[("tau2-dialog-min", 0)] == "1.2s"


def test_unit_lines_align_status_right_duration_left() -> None:
    buf = io.StringIO()
    clock = iter([0.0, 43.2, 43.2, 111.2])
    progress = RunProgress(
        suite_run_id="ca096a6f",
        dataset_label="official/demo@0.1.0",
        stderr=buf,
        use_bar=False,
        use_color=False,
        monotonic=lambda: next(clock),
        task_ids=["tau2-dialog-min", "terminal-jsonl-agg"],
    )
    progress.handle({"type": "suite_start", "todo": 2, "total": 2, "done": 0})
    for tid in ("tau2-dialog-min", "terminal-jsonl-agg"):
        progress.handle(
            {
                "type": "unit_start",
                "task_id": tid,
                "attempt_index": 0,
                "done": 0,
                "total": 2,
            }
        )
        progress.handle(
            {
                "type": "unit_done",
                "task_id": tid,
                "attempt_index": 0,
                "status": "PASS",
                "done": 1,
                "total": 2,
            }
        )
    progress.close()
    rows = [ln for ln in buf.getvalue().splitlines() if "PASS" in ln]
    assert len(rows) == 2
    pass_at = rows[0].index("PASS")
    assert rows[1].index("PASS") == pass_at
    time_at = pass_at + len("PASS") + 2
    assert rows[0][time_at:].startswith("43.2s")
    assert rows[1][time_at:].startswith("1m 08s")
    assert rows[0][pass_at - 1] == " "
    assert rows[1][pass_at - 1] == " "


def test_suite_recap_view_uses_ref_for_cache_root(tmp_path: Path) -> None:
    cache_root = (
        tmp_path
        / ".ageval"
        / "cache"
        / "datasets"
        / "official"
        / "demo"
        / "sha256_3c22b6b13e68abba0238eba778762eef14136ac61f55a1a59cce8a14e8a8e231"
    )
    text = format_suite_recap(
        {
            "suite_run_id": "ca096a6f",
            "dataset_id": "official/demo",
            "dataset_version": "0.1.0",
            "exit_code": 0,
            "counts": {"pass": 2, "fail": 0, "error": 0, "skipped": 0},
            "summary_path": str(cache_root / "summary.json"),
        },
        dataset_root=cache_root,
    )
    assert "ageval view official/demo@0.1.0" in text
    assert "ageval results upload-suite official/demo@0.1.0 --suite-run ca096a6f" in text
    next_block = text.split("next     ", 1)[-1]
    assert "sha256_3c22" not in next_block


def test_attempt_spinner_inert_without_tty() -> None:
    err = io.StringIO()
    with AttemptSpinner(task_id="terminal-jsonl-agg", stderr=err, use_bar=False):
        err.write("during")
    assert err.getvalue() == "during"


def test_attempt_spinner_transient_bar_leaves_no_residue() -> None:
    err = io.StringIO()
    with AttemptSpinner(task_id="terminal-jsonl-agg", stderr=err, use_bar=True, use_color=False):
        pass
    assert "terminal-jsonl-agg" not in err.getvalue()
    assert err.getvalue() in ("", "\n")


def test_run_progress_bar_description_shows_phase() -> None:
    err = io.StringIO()
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=True,
        use_color=False,
    )
    progress.handle({"type": "suite_start", "total": 1, "done": 0})
    progress.handle({"type": "unit_start", "task_id": "alpha", "attempt_index": 0})
    progress.handle(
        {"type": "unit_phase", "task_id": "alpha", "attempt_index": 0, "phase": "evaluate"}
    )
    assert progress._progress is not None and progress._bar_task is not None
    task = progress._progress.tasks[progress._bar_task]
    assert task.description == "alpha (evaluate)"
    assert "(evaluate)" in str(TextColumn("{task.description}").render(task))
    progress.handle(
        {"type": "unit_phase", "task_id": "alpha", "attempt_index": 0, "phase": "record"}
    )
    assert progress._progress.tasks[progress._bar_task].description == "alpha (record)"
    progress.close()


def test_run_progress_unit_phase_silent_without_tty() -> None:
    err = io.StringIO()
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=False,
        use_color=False,
    )
    progress.handle({"type": "unit_start", "task_id": "alpha", "attempt_index": 0})
    before = err.getvalue()
    progress.handle({"type": "unit_phase", "task_id": "alpha", "attempt_index": 0, "phase": "run"})
    assert err.getvalue() == before


def _stall_event(
    *, outcome: str, nxt: int, remaining: int, phase: str = "run"
) -> dict[str, object]:
    return {
        "type": "upstream_stall",
        "task_id": "alpha",
        "attempt_index": 0,
        "state": "upstream_stall",
        "outcome": outcome,
        "seconds_until_next": nxt,
        "remaining_budget": remaining,
        "phase": phase,
    }


def test_upstream_stall_prints_field_lines_when_the_bar_is_off() -> None:
    err = io.StringIO()
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=False,
        use_color=False,
    )
    progress.handle({"type": "unit_start", "task_id": "alpha", "attempt_index": 0})
    progress.handle(_stall_event(outcome="started", nxt=60, remaining=3600))
    progress.handle(_stall_event(outcome="wait", nxt=60, remaining=3540))
    progress.handle(_stall_event(outcome="resumed", nxt=0, remaining=3480))
    progress.handle(
        {
            "type": "unit_done",
            "task_id": "alpha",
            "attempt_index": 0,
            "status": "ERROR",
            "duration": "1s",
        }
    )
    lines = err.getvalue().strip().splitlines()
    stall = [line for line in lines if line.startswith("upstream_stall")]
    assert [line.split("outcome=")[-1] for line in stall] == ["started", "wait", "resumed"]
    assert "task=alpha" in stall[0]
    assert "state=upstream_stall" in stall[0]
    assert "next=60" in stall[1]
    assert "remaining=3540" in stall[1]
    assert "ERROR" in lines[-1]
    assert "outcome=" not in lines[-1]


def test_upstream_stall_bar_uses_the_phase_slot() -> None:
    err = io.StringIO()
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=True,
        use_color=False,
    )
    progress.handle({"type": "suite_start", "total": 1, "done": 0})
    progress.handle({"type": "unit_start", "task_id": "alpha", "attempt_index": 0})
    progress.handle(
        {"type": "unit_phase", "task_id": "alpha", "attempt_index": 0, "phase": "upstream_stall"}
    )
    assert progress._progress is not None and progress._bar_task is not None
    assert progress._progress.tasks[progress._bar_task].description == "alpha (upstream_stall)"
    progress.handle(_stall_event(outcome="resumed", nxt=0, remaining=3000, phase="run"))
    assert progress._progress.tasks[progress._bar_task].description == "alpha (run)"
    assert "upstream_stall task=" not in err.getvalue()
    progress.close()


def test_attempt_spinner_stall_updates_the_bar_and_prints_fields_without_one() -> None:
    err = io.StringIO()
    spinner = AttemptSpinner(task_id="alpha", stderr=err, use_bar=True, use_color=False)
    with spinner:
        assert spinner._progress is not None and spinner._bar_task is not None
        spinner.stall(_stall_event(outcome="started", nxt=60, remaining=3600))
        assert spinner._progress.tasks[spinner._bar_task].description == "alpha (upstream_stall)"
        spinner.stall(_stall_event(outcome="resumed", nxt=0, remaining=3480, phase="evaluate"))
        assert spinner._progress.tasks[spinner._bar_task].description == "alpha (evaluate)"
    assert "upstream_stall task=" not in err.getvalue()

    plain = io.StringIO()
    quiet = AttemptSpinner(task_id="alpha", stderr=plain, use_bar=False)
    quiet.stall(_stall_event(outcome="budget_exhausted", nxt=0, remaining=0))
    text = plain.getvalue().strip()
    assert text.startswith("upstream_stall task=alpha")
    assert "state=upstream_stall" in text
    assert "outcome=budget_exhausted" in text
    assert "next=0" in text
    assert "remaining=0" in text


def test_attempt_spinner_phase_updates_description() -> None:
    err = io.StringIO()
    spinner = AttemptSpinner(task_id="alpha", stderr=err, use_bar=True, use_color=False)
    with spinner:
        assert spinner._progress is not None and spinner._bar_task is not None
        spinner.phase("started", "environment")
        assert spinner._progress.tasks[spinner._bar_task].description == "alpha (environment)"
        spinner.phase("finished", "environment")
        assert spinner._progress.tasks[spinner._bar_task].description == "alpha (environment)"
        spinner.phase("started", "run")
        task = spinner._progress.tasks[spinner._bar_task]
        assert task.description == "alpha (run)"
        assert "(run)" in str(TextColumn("{task.description}").render(task))


def test_suite_bar_elapsed_column_shows_unit_time_and_total() -> None:
    err = io.StringIO()
    clock = {"t": 100.0}
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=True,
        use_color=False,
        monotonic=lambda: clock["t"],
    )
    progress.handle({"type": "suite_start", "total": 2, "done": 0})
    clock["t"] = 110.0
    progress.handle({"type": "unit_start", "task_id": "alpha", "attempt_index": 0})
    clock["t"] = 125.0
    assert progress._progress is not None and progress._bar_task is not None
    column = _SuiteElapsedColumn(progress)
    rendered = str(column.render(progress._progress.tasks[progress._bar_task]))
    # Current unit clock (110 -> 125) leads; the suite total (100 -> 125) follows dimmed.
    assert "15s" in rendered
    assert "(total 25s)" in rendered
    progress.close()


def test_suite_bar_elapsed_without_running_unit_shows_dash() -> None:
    err = io.StringIO()
    clock = {"t": 100.0}
    progress = RunProgress(
        suite_run_id="s",
        dataset_label="d",
        stderr=err,
        use_bar=True,
        use_color=False,
        monotonic=lambda: clock["t"],
    )
    progress.handle({"type": "suite_start", "total": 1, "done": 0})
    clock["t"] = 130.0
    assert progress._progress is not None and progress._bar_task is not None
    column = _SuiteElapsedColumn(progress)
    rendered = str(column.render(progress._progress.tasks[progress._bar_task]))
    assert rendered.startswith("-")
    assert "(total 30s)" in rendered
    progress.close()
