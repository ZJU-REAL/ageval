"""``ageval results analyze`` — read sealed evidence, write analysis artifacts.

Single-run failures raise and leave no report. A suite writes the reports that
succeeded, records skip and error rows, then raises when any selected attempt
failed. Nothing here changes PASS or ``evaluation/checks.json``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ageval.application.analysis.errors import (
    ANALYSIS_AGENT,
    ANALYSIS_FAILED,
    ANALYSIS_INPUT,
    ANALYSIS_SCOPE,
)
from ageval.application.analysis.hack import build_hack
from ageval.application.analysis.read import attempt_status, read_json_object
from ageval.application.analysis.review import RUBRIC_IDS, run_review
from ageval.application.analysis.session import analysis_agent
from ageval.application.analysis.stats import build_stats
from ageval.application.suite import document as suite_document
from ageval.config.errors import ConfigError
from ageval.environments.protocol import WORKSPACE_PATH
from ageval.evidence.analysis import (
    REPORT_SCHEMA,
    SUMMARY_SCHEMA,
    is_analyzer,
    report_path,
    report_rel,
    summary_path,
    summary_rel,
    write_analysis_json,
)
from ageval.evidence.attempt_record import read_attempt_result
from ageval.evidence.locators import resolve_attempt_run_dir, safe_id_segment
from ageval.evidence.trajectory import TRAJECTORY_FILENAME
from ageval.plugins.agent_result import AgentResult

_STATUS_NAMES = ("PASS", "FAIL", "ERROR")
_REVIEW_INPUTS = ("result.json", TRAJECTORY_FILENAME, "summary.json")
_INVOKE_TIMEOUT = 120.0


class _AgentCall:
    """One HTTP invoke. Opens a local box only for that call."""

    def __init__(
        self,
        dataset_root: Path,
        agent: str,
        *,
        model: str | None,
        base_url: str | None,
    ) -> None:
        self.dataset_root = dataset_root
        self.agent = agent
        self.model = model
        self.base_url = base_url
        self.kind = ""

    def __call__(self, prompt: str) -> AgentResult:
        dataset_root = self.dataset_root
        agent = self.agent
        model = self.model
        base_url = self.base_url

        async def _once() -> AgentResult:
            async with analysis_agent(
                dataset_root,
                agent,
                model=model,
                base_url=base_url,
            ) as bound:
                self.kind = bound.executor_kind
                result = bound.executor.invoke(prompt, timeout=_INVOKE_TIMEOUT)
                if not isinstance(result, AgentResult):
                    raise ConfigError(
                        ANALYSIS_AGENT,
                        "analysis agent returned an unexpected result",
                        location="--agent",
                    )
                return result

        return asyncio.run(_once())


class AnalyzeCommand:
    """Post-run stats, hack, and review over one run or one suite."""

    def analyze(
        self,
        dataset: Path,
        *,
        run_id: str | None = None,
        suite_run_id: str | None = None,
        analyzer: str = "stats",
        no_llm: bool = False,
        include_all: bool = False,
        statuses: list[str] | None = None,
        agent: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        root = Path(dataset).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise ConfigError(
                ANALYSIS_INPUT,
                f"dataset root is not a directory: {root}",
                location=str(root),
            )
        name = _analyzer_name(analyzer)
        agent_text = agent.strip() if isinstance(agent, str) and agent.strip() else None
        model_text = model.strip() if isinstance(model, str) and model.strip() else None
        base_text = base_url.strip() if isinstance(base_url, str) and base_url.strip() else None
        allowed = _scope(
            name,
            no_llm=no_llm,
            include_all=include_all,
            statuses=statuses,
            agent=agent_text,
            model=model_text,
            base_url=base_text,
        )
        if agent_text:
            from ageval.application.analysis.session import load_analysis_profile

            load_analysis_profile(agent_text, model=model_text, base_url=base_text)
        run_text = (run_id or "").strip()
        suite_text = (suite_run_id or "").strip()
        if bool(run_text) == bool(suite_text):
            raise ConfigError(
                ANALYSIS_INPUT,
                "pass exactly one of --run or --suite-run",
                location="--run",
            )
        if run_text:
            return self._one_run(
                root,
                run_id=run_text,
                analyzer=name,
                allowed=allowed,
                no_llm=no_llm,
                agent=agent_text,
                model=model_text,
                base_url=base_text,
            )
        return self._suite(
            root,
            suite_run_id=suite_text,
            analyzer=name,
            allowed=allowed,
            no_llm=no_llm,
            agent=agent_text,
            model=model_text,
            base_url=base_text,
        )

    def _one_run(
        self,
        root: Path,
        *,
        run_id: str,
        analyzer: str,
        allowed: set[str] | None,
        no_llm: bool,
        agent: str | None,
        model: str | None,
        base_url: str | None,
    ) -> dict[str, Any]:
        run_dir = resolve_attempt_run_dir(root, run_id)
        status = attempt_status(run_dir)
        _require_scope(status, allowed, run_id=run_id)
        doc = self._build(
            root,
            run_dir,
            run_id=run_id,
            task_id=_task_id(run_dir, None),
            analyzer=analyzer,
            no_llm=no_llm,
            agent=agent,
            model=model,
            base_url=base_url,
        )
        path = report_path(run_dir, analyzer)
        write_analysis_json(path, doc)
        return {
            "ok": True,
            "kind": "analysis",
            "schema": REPORT_SCHEMA,
            "analyzer": analyzer,
            "run_id": run_id,
            "attempt_status": doc.get("attempt_status"),
            "report": report_rel(analyzer),
            "path": str(path),
        }

    def _suite(
        self,
        root: Path,
        *,
        suite_run_id: str,
        analyzer: str,
        allowed: set[str] | None,
        no_llm: bool,
        agent: str | None,
        model: str | None,
        base_url: str | None,
    ) -> dict[str, Any]:
        sid = safe_id_segment(suite_run_id, field="suite_run_id")
        summary = suite_document.load_suite_summary(root, sid)
        rows = suite_document.attempt_rows(summary)
        if not rows:
            raise ConfigError(
                ANALYSIS_INPUT,
                f"suite {sid} has no attempts to analyze",
                location=str(suite_document.summary_path(root, sid)),
            )
        suite_dir = suite_document.suite_dir(root, sid)
        records: list[dict[str, Any]] = []
        ok_docs: list[dict[str, Any]] = []
        for row in rows:
            record, doc = self._suite_attempt(
                root,
                row,
                analyzer=analyzer,
                allowed=allowed,
                no_llm=no_llm,
                agent=agent,
                model=model,
                base_url=base_url,
            )
            records.append(record)
            if doc is not None:
                ok_docs.append(doc)
        counts = {
            "ok": sum(1 for item in records if item["outcome"] == "ok"),
            "skipped": sum(1 for item in records if item["outcome"] == "skipped"),
            "error": sum(1 for item in records if item["outcome"] == "error"),
        }
        document = {
            "schema": SUMMARY_SCHEMA,
            "analyzer": analyzer,
            "suite_run_id": sid,
            "created_at": _now(),
            "filter": None if allowed is None else {"statuses": sorted(allowed)},
            "counts": counts,
            "attempts": records,
            "rollup": _rollup(analyzer, ok_docs),
        }
        path = summary_path(suite_dir, analyzer)
        write_analysis_json(path, document)
        if counts["error"]:
            first = next(item for item in records if item["outcome"] == "error")
            raise ConfigError(
                ANALYSIS_FAILED,
                f"{counts['error']} attempt(s) failed; summary at {path}; "
                f"first error: {first['error']}",
                location=str(path),
            )
        return {
            "ok": True,
            "kind": "analysis",
            "schema": SUMMARY_SCHEMA,
            "analyzer": analyzer,
            "suite_run_id": sid,
            "summary": summary_rel(analyzer),
            "path": str(path),
            "counts": counts,
        }

    def _suite_attempt(
        self,
        root: Path,
        row: dict[str, Any],
        *,
        analyzer: str,
        allowed: set[str] | None,
        no_llm: bool,
        agent: str | None,
        model: str | None,
        base_url: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        run_id = str(row.get("run_id") or "").strip()
        task_id = str(row.get("task_id") or "").strip() or None
        if not run_id:
            return _record(run_id, task_id, "error", None, "attempt is missing run_id", None), None
        try:
            run_dir = resolve_attempt_run_dir(root, run_id)
        except ConfigError as exc:
            status = _status_text(row.get("status"))
            if not _in_scope(status, allowed):
                return _record(run_id, task_id, "skipped", status, None, None), None
            return _record(run_id, task_id, "error", status, str(exc), None), None
        status = attempt_status(run_dir, fallback=_status_text(row.get("status")))
        if not _in_scope(status, allowed):
            return _record(run_id, task_id, "skipped", status, None, None), None
        try:
            doc = self._build(
                root,
                run_dir,
                run_id=run_id,
                task_id=_task_id(run_dir, task_id),
                analyzer=analyzer,
                no_llm=no_llm,
                agent=agent,
                model=model,
                base_url=base_url,
            )
        except ConfigError as exc:
            return _record(run_id, task_id, "error", status, str(exc), None), None
        write_analysis_json(report_path(run_dir, analyzer), doc)
        return _record(run_id, task_id, "ok", status, None, report_rel(analyzer)), doc

    def _build(
        self,
        root: Path,
        run_dir: Path,
        *,
        run_id: str,
        task_id: str | None,
        analyzer: str,
        no_llm: bool,
        agent: str | None,
        model: str | None,
        base_url: str | None,
    ) -> dict[str, Any]:
        if analyzer == "stats":
            body = build_stats(run_dir, run_id=run_id, task_id=task_id)
        elif analyzer == "hack":
            caller = _AgentCall(root, agent, model=model, base_url=base_url) if agent else None
            body = build_hack(
                run_dir,
                run_id=run_id,
                task_id=task_id,
                no_llm=no_llm,
                invoke=caller,
            )
        else:
            _require_review_inputs(run_dir)
            if not agent:
                raise ConfigError(
                    ANALYSIS_AGENT,
                    "--agent is required for review",
                    location="--agent",
                )
            findings, kind, bound_model = _review_attempt(
                root,
                run_dir,
                agent=agent,
                model=model,
                base_url=base_url,
            )
            body = {
                "run_id": run_id,
                "attempt_status": attempt_status(run_dir),
                "rubric": list(RUBRIC_IDS),
                "findings": findings,
                "agent": {"executor": kind, "model": bound_model},
            }
            if task_id:
                body["task_id"] = task_id
        return _stamp(body, analyzer=analyzer, run_id=run_id)


def _review_attempt(
    root: Path,
    run_dir: Path,
    *,
    agent: str,
    model: str | None,
    base_url: str | None,
) -> tuple[list[dict[str, Any]], str, str]:
    async def _once() -> tuple[list[dict[str, Any]], str, str]:
        async with analysis_agent(root, agent, model=model, base_url=base_url) as bound:
            await bound.host.upload(run_dir, f"{WORKSPACE_PATH}/attempt")
            findings = run_review(bound.executor, bound.host)
            return findings, bound.executor_kind, bound.model

    return asyncio.run(_once())


def _stamp(body: dict[str, Any], *, analyzer: str, run_id: str) -> dict[str, Any]:
    doc = dict(body)
    doc["schema"] = REPORT_SCHEMA
    doc["analyzer"] = analyzer
    doc["run_id"] = run_id
    doc["created_at"] = _now()
    return doc


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _analyzer_name(analyzer: str) -> str:
    name = (analyzer or "").strip() or "stats"
    if not is_analyzer(name):
        raise ConfigError(
            ANALYSIS_INPUT,
            f"unknown analyzer {analyzer!r}",
            location="--analyzer",
        )
    return name


def _scope(
    analyzer: str,
    *,
    no_llm: bool,
    include_all: bool,
    statuses: list[str] | None,
    agent: str | None,
    model: str | None,
    base_url: str | None,
) -> set[str] | None:
    if (model or base_url) and not agent:
        raise ConfigError(
            ANALYSIS_AGENT,
            "--model and --base-url require --agent",
            location="--agent",
        )
    parsed = _parse_statuses(statuses)
    if analyzer == "stats" and (no_llm or include_all or parsed or agent or model or base_url):
        code = ANALYSIS_AGENT if agent or model or base_url else ANALYSIS_SCOPE
        raise ConfigError(
            code,
            "stats does not accept --no-llm, --all, --status, or --agent",
            location="--analyzer",
        )
    if no_llm and analyzer != "hack":
        raise ConfigError(
            ANALYSIS_SCOPE,
            "--no-llm is only valid for hack",
            location="--no-llm",
        )
    if include_all and parsed:
        raise ConfigError(
            ANALYSIS_SCOPE,
            "--all and --status cannot be used together",
            location="--status",
        )
    if analyzer == "review" and not agent:
        raise ConfigError(
            ANALYSIS_AGENT,
            "--agent is required for review",
            location="--agent",
        )
    if include_all or (analyzer == "review" and not parsed):
        return None
    if parsed:
        return set(parsed)
    if analyzer == "hack":
        return {"PASS"}
    return None


def _parse_statuses(raw: list[str] | None) -> list[str]:
    found: list[str] = []
    for item in raw or []:
        text = str(item).strip().upper()
        if not text:
            continue
        if text not in _STATUS_NAMES:
            raise ConfigError(
                ANALYSIS_SCOPE,
                f"status must be PASS, FAIL, or ERROR; got {item!r}",
                location="--status",
            )
        if text not in found:
            found.append(text)
    return found


def _in_scope(status: str | None, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    return bool(status) and status in allowed


def _require_scope(status: str | None, allowed: set[str] | None, *, run_id: str) -> None:
    if _in_scope(status, allowed):
        return
    if status is None and allowed == {"PASS"}:
        message = "attempt status is missing; hack analyzes PASS unless --all"
    else:
        message = (
            f"attempt status {status} is outside the analysis scope "
            f"({', '.join(sorted(allowed or []))})"
        )
    raise ConfigError(ANALYSIS_SCOPE, message, location=run_id)


def _require_review_inputs(run_dir: Path) -> None:
    if any((run_dir / name).is_file() for name in _REVIEW_INPUTS):
        return
    raise ConfigError(
        ANALYSIS_INPUT,
        "review needs result.json, trajectory.jsonl, or summary.json",
        location=str(run_dir),
    )


def _status_text(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().upper()
    if text in _STATUS_NAMES:
        return text
    return None


def _task_id(run_dir: Path, fallback: str | None) -> str | None:
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    for doc in (
        read_attempt_result(run_dir),
        read_json_object(run_dir / "summary.json"),
        read_json_object(run_dir / "lock.json"),
    ):
        if not isinstance(doc, dict):
            continue
        raw = doc.get("task_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _record(
    run_id: str,
    task_id: str | None,
    outcome: str,
    status: str | None,
    error: str | None,
    report: str | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "task_id": task_id,
        "outcome": outcome,
        "status": status,
        "error": error,
        "report": report,
    }


def _rollup(analyzer: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    if analyzer == "stats":
        return _rollup_stats(docs)
    if analyzer == "hack":
        return _rollup_hack(docs)
    return _rollup_review(docs)


def _rollup_stats(docs: list[dict[str, Any]]) -> dict[str, Any]:
    invoke = tool = failures = 0
    stalls = 0
    stall_known = bool(docs)
    for doc in docs:
        metrics = doc.get("metrics")
        if not isinstance(metrics, dict):
            continue
        invoke += int(metrics.get("invoke_count") or 0)
        tool += int(metrics.get("tool_call_count") or 0)
        failures += int(metrics.get("tool_failure_count") or 0)
        stall = metrics.get("upstream_stall_count")
        if isinstance(stall, int):
            stalls += stall
        else:
            stall_known = False
    return {
        "invoke_count": invoke,
        "tool_call_count": tool,
        "tool_failure_count": failures,
        "tool_failure_rate": round(failures / tool, 4) if tool else None,
        "upstream_stall_count": stalls if stall_known else None,
    }


def _rollup_hack(docs: list[dict[str, Any]]) -> dict[str, Any]:
    is_hack = suspects = undecided = 0
    for doc in docs:
        stage1 = doc.get("stage1")
        if isinstance(stage1, dict):
            suspects += int(stage1.get("suspect_count") or 0)
        if "is_hack" not in doc:
            undecided += 1
        elif doc.get("is_hack") is True:
            is_hack += 1
    return {"is_hack": is_hack, "suspects": suspects, "undecided": undecided}


def _rollup_review(docs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {rubric: {} for rubric in RUBRIC_IDS}
    for doc in docs:
        findings = doc.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            rubric = finding.get("rubric")
            judgment = finding.get("judgment")
            if rubric not in counts or not isinstance(judgment, str):
                continue
            bucket = counts[str(rubric)]
            bucket[judgment] = bucket.get(judgment, 0) + 1
    return counts
