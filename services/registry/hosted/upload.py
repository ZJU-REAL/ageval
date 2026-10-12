"""Upload a finished hosted suite through the existing results use case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.hosted.rows import JobRow

from ageval.application.registry_ops.results_command import ResultsCommands
from ageval.registry.client import RegistryError


class _InProcessResults:
    """RegistryClient surface backed by ResultService. No token is minted."""

    def __init__(self, results: Any, auth: TokenInfo) -> None:
        self._results = results
        self._auth = auth

    def upload_suite(self, **kwargs: Any) -> dict[str, Any]:
        meta = {
            "suite_run_id": kwargs["suite_run_id"],
            "dataset_id": kwargs["dataset_id"],
            "dataset_version": kwargs["dataset_version"],
            "visibility": kwargs["visibility"],
            "pass_rate": kwargs["pass_rate"],
            "mean_score": kwargs["mean_score"],
            "metrics": kwargs["metrics"],
            "task_refs": kwargs["task_refs"],
            "agent_label": kwargs["agent_label"],
            "model_label": kwargs["model_label"],
            "exit_code": kwargs["exit_code"],
            "blob_digest": kwargs["blob_digest"],
            "size": kwargs["size"],
        }
        if kwargs.get("replace"):
            meta["replace"] = True
        for key in (
            "config_fingerprint",
            "config_homogeneous",
            "actors_summary",
            "job_overlay",
            "plugins",
        ):
            if kwargs.get(key) is not None:
                meta[key] = kwargs[key]
        return self._call("upload_suite", meta, kwargs["archive"])

    def upload_attempt(self, **kwargs: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "run_id": kwargs["run_id"],
            "dataset_id": kwargs["dataset_id"],
            "dataset_version": kwargs["dataset_version"],
            "task_id": kwargs["task_id"],
            "lock_digest": kwargs["lock_digest"],
            "status": kwargs["status"],
            "visibility": kwargs["visibility"],
            "blob_digest": kwargs["blob_digest"],
            "size": kwargs["size"],
            "error": kwargs.get("error"),
        }
        if kwargs.get("suite_run_id"):
            meta["suite_run_id"] = kwargs["suite_run_id"]
        if kwargs.get("replace"):
            meta["replace"] = True
        if kwargs.get("environment"):
            meta["environment"] = kwargs["environment"]
        if kwargs.get("agent_label"):
            meta["agent_label"] = kwargs["agent_label"]
        if kwargs.get("model_label"):
            meta["model_label"] = kwargs["model_label"]
        if kwargs.get("score") is not None:
            meta["score"] = kwargs["score"]
        if isinstance(kwargs.get("limit"), str) and kwargs["limit"].strip():
            meta["limit"] = kwargs["limit"].strip()
        return self._call("upload_attempt", meta, kwargs["archive"])

    def _call(self, method: str, meta: dict[str, Any], archive: Path) -> dict[str, Any]:
        try:
            fn = getattr(self._results, method)
            return fn(meta=meta, archive=archive, auth=self._auth)
        except RegistryAppError as exc:
            raise RegistryError(exc.error, exc.message, status=exc.http_status) from exc


def upload_hosted_suite(state: Any, job: JobRow, dataset_root: Path, suite_run_id: str) -> None:
    """Pack the suite (and its attempts) as a private result owned by the submitter."""
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id=job.created_by)
    client = _InProcessResults(state.results, auth)
    ResultsCommands(lambda **_kwargs: client).upload_suite_result(
        dataset_root,
        suite_run_id=suite_run_id,
        public=False,
        with_attempts=True,
    )
