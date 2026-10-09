"""Post-run analysis artifact layout.

Paths live here. Analyzers read sealed evidence and write only these files.
They do not score, and they do not upload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ANALYSIS_DIR = "analysis"
REPORT_FILENAME = "report.json"
SUMMARY_FILENAME = "summary.json"

ANALYZERS: tuple[str, ...] = ("stats", "hack", "review")

REPORT_SCHEMA = "ageval.analysis.report/1"
SUMMARY_SCHEMA = "ageval.analysis.summary/1"


def is_analyzer(name: str) -> bool:
    return name in ANALYZERS


def is_analysis_rel(rel: str) -> bool:
    """True when *rel* (posix, run-dir or suite-dir relative) is under ``analysis/``."""
    parts = Path(rel).parts
    return bool(parts) and parts[0] == ANALYSIS_DIR


def report_rel(analyzer: str) -> str:
    return f"{ANALYSIS_DIR}/{analyzer}/{REPORT_FILENAME}"


def summary_rel(analyzer: str) -> str:
    return f"{ANALYSIS_DIR}/{analyzer}/{SUMMARY_FILENAME}"


def report_path(run_dir: Path | str, analyzer: str) -> Path:
    return Path(run_dir) / ANALYSIS_DIR / analyzer / REPORT_FILENAME


def summary_path(suite_dir: Path | str, analyzer: str) -> Path:
    return Path(suite_dir) / ANALYSIS_DIR / analyzer / SUMMARY_FILENAME


def write_analysis_json(path: Path, doc: dict[str, Any]) -> Path:
    """Atomically write one analysis JSON object."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    raw = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_attempt_reports(run_dir: Path | str) -> list[dict[str, Any]]:
    """Reports that exist under one Attempt, in analyzer order.

    A present file that is not a JSON object is returned with ``report: null``
    and a note. Missing files are omitted.
    """
    root = Path(run_dir)
    found: list[dict[str, Any]] = []
    for name in ANALYZERS:
        path = report_path(root, name)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            found.append(
                {"analyzer": name, "report": None, "note": "report.json is not valid JSON"}
            )
            continue
        if not isinstance(data, dict):
            found.append({"analyzer": name, "report": None, "note": "report.json is not an object"})
            continue
        found.append({"analyzer": name, "report": data, "note": None})
    return found
