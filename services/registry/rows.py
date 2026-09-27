"""Row dataclasses shared by the Registry aggregate stores."""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------



@dataclass(frozen=True, slots=True)
class AttemptResultRow:
    """Sealed Attempt evidence bundle metadata (not a Dataset package)."""

    run_id: str
    dataset_id: str
    task_id: str
    lock_digest: str
    status: str
    visibility: str
    blob_digest: str
    size: int
    created_at: float
    dataset_version: str = ""
    uploaded_by: str = ""
    # Optional link to parent suite/job (#43); empty on standalone uploads.
    suite_run_id: str = ""
    environment: str = ""
    agent_label: str = ""
    model_label: str = ""
    score: float | None = None
    error_json: str | None = None
    limit_name: str | None = None


@dataclass(frozen=True, slots=True)
class SuiteResultRow:
    """Suite/job result row: aggregates + per-task refs (not suite PASS).

    Observational leaderboard input for Hub SPA (#22 S5). PASS remains
    per-task evaluator only.
    """

    suite_run_id: str
    dataset_id: str
    dataset_version: str
    visibility: str
    pass_rate: float
    mean_score: float
    metrics_json: str
    tasks_json: str
    agent_label: str
    model_label: str
    blob_digest: str
    size: int
    exit_code: int
    created_at: float
    # #42 config comparability (optional; empty/default on legacy rows)
    config_json: str = "{}"
    uploaded_by: str = ""
    complete: bool = False
    bound_kind: str = "unknown"
    task_set_digest: str = ""
    board_listed: bool = False


@dataclass(frozen=True, slots=True)
class ResourceRequestRow:
    request_id: str
    kind: str
    status: str
    suite_run_id: str
    dataset_id: str
    applicant: str
    owner_org_id: str
    agent_ref: str
    created_at: float
    decided_at: float | None = None
    decided_by: str = ""
    canonical_model: str = ""







@dataclass(frozen=True, slots=True)
class ResultShareRow:
    result_kind: str  # attempt | suite
    result_id: str
    target_type: str  # org | user
    target_id: str
    created_at: float


@dataclass(frozen=True, slots=True)
class SnapshotShareRow:
    """One-shot read link. Not a suite visibility or result_shares row."""

    token: str
    owner_user_id: str
    suite_run_id: str
    dataset_id: str
    dataset_version: str
    blob_digest: str
    size: int
    summary_json: str
    created_at: float
    run_id: str = ""



# ---------------------------------------------------------------------------
# Metadata (packages + attempt results + orgs + shares)
