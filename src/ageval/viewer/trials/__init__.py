"""Attempt / trial evidence APIs for the local viewer (issue #26 / #31).

Resolves ``run_id`` → evidence root under the opened Dataset sandbox and exposes
read-only meta, file tree, file preview, and trajectory steps. Tabs are derived
from files that exist — never fabricated. Trajectory is observational, not PASS.

Package layout (chore #31): paths · usage · surface · meta · fs · trajectory.
"""

from __future__ import annotations

from ageval.viewer.trials.checks import trial_evaluation_checks, trial_package_file
from ageval.viewer.trials.constants import (
    MAX_FILE_BYTES,
    MAX_JSONL_LINE,
    MAX_TRAJECTORY_STEPS,
    MAX_TREE_ENTRIES,
    TEXT_SUFFIXES,
)
from ageval.viewer.trials.fs import trial_file, trial_tree
from ageval.viewer.trials.meta import get_trial, list_task_trials
from ageval.viewer.trials.paths import parse_query, resolve_evidence_root
from ageval.viewer.trials.trajectory import trial_evaluation_observation, trial_trajectory
from ageval.viewer.trials.usage import _usage_summary_for_actor

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_JSONL_LINE",
    "MAX_TRAJECTORY_STEPS",
    "MAX_TREE_ENTRIES",
    "TEXT_SUFFIXES",
    "get_trial",
    "list_task_trials",
    "parse_query",
    "resolve_evidence_root",
    "trial_file",
    "trial_evaluation_checks",
    "trial_evaluation_observation",
    "trial_package_file",
    "trial_trajectory",
    "trial_tree",
    "_usage_summary_for_actor",
]
