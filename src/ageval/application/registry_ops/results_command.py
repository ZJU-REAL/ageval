"""Application use cases for Attempt + Suite result upload / get / list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.application.suite import ensure_suite_metrics, ensure_suite_task_refs
from ageval.config.dataset import load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.evidence.locators import default_runs_root, resolve_attempt_run_dir
from ageval.registry.client import RegistryError
from ageval.registry.resolve import resolve_dataset_root
from ageval.registry.results_archive import (
    build_attempt_archive,
    build_suite_archive,
    extract_attempt_archive,
    extract_suite_archive,
)


def _attempt_job_fields(run_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Labels Hub Jobs needs for a standalone Attempt (not a suite row)."""
    from ageval.config.profiles import display_labels_from_overlay, environment_from_overlay

    lock: dict[str, Any] = {}
    lock_path = run_dir / "lock.json"
    if lock_path.is_file():
        try:
            loaded = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            lock = loaded
    overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    environment = ""
    for raw in (
        lock.get("environment"),
        meta.get("kind"),
        environment_from_overlay(overlay),
    ):
        if isinstance(raw, str) and raw.strip():
            environment = raw.strip()
            break
    agent_label, model_label = display_labels_from_overlay(overlay)
    task_id = str(meta.get("task_id") or lock.get("task_id") or "").strip()
    raw_score = meta.get("score")
    score = (
        None
        if isinstance(raw_score, bool) or not isinstance(raw_score, int | float)
        else float(raw_score)
    )
    return {
        "task_id": task_id,
        "environment": environment,
        "agent_label": agent_label,
        "model_label": model_label,
        "score": score,
    }


def _read_run_meta(run_dir: Path) -> dict[str, Any]:
    from ageval.evidence.attempt_record import read_attempt_result

    meta: dict[str, Any] = {}
    result = read_attempt_result(run_dir)
    if result:
        meta.update(result)
    for name in ("status.json", "summary.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            meta.update(data)
    return meta


def _resolve_suite_dir(dataset_root: Path, suite_run_id: str) -> Path:
    root = dataset_root.expanduser().resolve(strict=False)
    candidate = root / ".ageval" / "suite-runs" / suite_run_id
    if candidate.is_dir():
        return candidate
    raise ConfigError(
        "invalid_package",
        f"suite directory not found: {candidate}",
        location=str(candidate),
    )


def _load_suite_summary(suite_dir: Path) -> dict[str, Any]:
    path = suite_dir / "summary.json"
    if not path.is_file():
        raise ConfigError(
            "invalid_package",
            f"suite summary missing: {path}",
            location=str(path),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(
            "invalid_package",
            f"unreadable suite summary: {exc}",
            location=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            "invalid_package",
            "suite summary must be a JSON object",
            location=str(path),
        )
    return data


def _task_rows_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("tasks")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]


def _suite_metrics_and_refs(summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve metrics + task_refs, recomputing pass@k / n,c when recoverable (#60 A).

    Recompute is local-only (list/get/upload). Hub never becomes the live
    pass@k authority. Missing k maps with complete ``attempts[]`` or per-task
    ``n``/``c`` are restored before upload.
    """
    task_rows = _task_rows_from_summary(summary)
    metrics = ensure_suite_metrics(summary, task_rows=task_rows)
    raw_refs = summary.get("task_refs")
    existing: list[dict[str, Any]] | None = None
    if isinstance(raw_refs, list):
        existing = [t for t in raw_refs if isinstance(t, dict)]
    task_refs = ensure_suite_task_refs(
        summary,
        task_rows=task_rows,
        existing_refs=existing,
    )
    return metrics, task_refs


def _config_fields_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Project #42/#59 config fingerprint + job_overlay (absent on legacy summaries)."""
    actors = summary.get("actors_summary")
    if not isinstance(actors, list):
        actors = []
    out: dict[str, Any] = {
        "actors_summary": [a for a in actors if isinstance(a, dict)],
    }
    fp = summary.get("config_fingerprint")
    if isinstance(fp, str) and fp.strip():
        out["config_fingerprint"] = fp.strip()
    if "config_homogeneous" in summary:
        out["config_homogeneous"] = bool(summary.get("config_homogeneous"))
    # #59 secret-free job binding for Hub rehydrate (locators only).
    overlay = summary.get("job_overlay")
    if isinstance(overlay, dict) and overlay:
        out["job_overlay"] = overlay
    plugins = summary.get("plugins")
    if isinstance(plugins, list) and plugins:
        out["plugins"] = [p for p in plugins if isinstance(p, dict)]
    return out


def _local_suite_item(summary: dict[str, Any], *, suite_dir: Path) -> dict[str, Any]:
    metrics, task_refs = _suite_metrics_and_refs(summary)
    item: dict[str, Any] = {
        "suite_run_id": summary.get("suite_run_id") or suite_dir.name,
        "dataset_id": summary.get("dataset_id"),
        "dataset_version": summary.get("dataset_version"),
        "visibility": "local",
        "pass_rate": metrics.get("pass_rate"),
        "mean_score": metrics.get("mean_score"),
        "metrics": metrics,
        "task_refs": task_refs,
        "agent_label": summary.get("agent_label") or "",
        "model_label": summary.get("model_label") or "",
        "exit_code": summary.get("exit_code"),
        "summary_path": str(suite_dir / "summary.json"),
        "source": "local",
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    item.update(_config_fields_from_summary(summary))
    return item


def _run_ids_from_task_refs(task_refs: list[dict[str, Any]]) -> list[str]:
    """Unique non-empty run_ids from suite task_refs (stable order).

    Prefers ``attempt_run_ids`` (all k samples) when present so
    ``--with-attempts`` can upload the full multi-attempt set (#60 A3).
    Falls back to the primary ``run_id`` per task.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: object) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    for ref in task_refs:
        ids = ref.get("attempt_run_ids")
        if isinstance(ids, list) and ids:
            for rid in ids:
                _add(rid)
        else:
            _add(ref.get("run_id"))
    return out


class ResultsCommands:
    def __init__(self, client_factory: Any) -> None:
        self._client_factory = client_factory

    def upload_attempt_result(
        self,
        dataset_root: Path,
        *,
        run_id: str,
        public: bool = False,
        suite_run_id: str | None = None,
        registry_url: str | None = None,
        allow_existing: bool = False,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Pack ``.ageval/runs/<run_id>`` and POST to results store.

        When *allow_existing* is true, a registry ``conflict`` (same run_id already
        uploaded) is treated as success with ``already_exists: true`` (idempotent
        re-upload / suite --with-attempts retry). *replace* overwrites the same
        run_id for the owner only (explicit; never silent).
        """
        if replace and allow_existing:
            raise ConfigError(
                "invalid_request",
                "replace and allow_existing are mutually exclusive",
                location="registry",
            )
        root = dataset_root.expanduser().resolve(strict=False)
        try:
            manifest = load_dataset_manifest(root)
            dataset_id = manifest.dataset_id
        except ConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConfigError("invalid_package", str(exc), location=str(root)) from exc

        run_dir = resolve_attempt_run_dir(root, run_id)
        archive_bytes, blob_digest, size = build_attempt_archive(run_dir, run_id=run_id)
        meta = _read_run_meta(run_dir)
        job = _attempt_job_fields(run_dir, meta)
        task_id = str(job.get("task_id") or "")
        lock_digest = str(meta.get("lock_digest") or meta.get("digest") or "")
        status = str(meta.get("status") or meta.get("verdict") or meta.get("outcome") or "")
        suite_link = (suite_run_id or str(meta.get("suite_run_id") or "")).strip() or None

        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ageval-att-") as tmp:
            archive = Path(tmp) / "attempt.tar.gz"
            archive.write_bytes(archive_bytes)
            try:
                info = client.upload_attempt(
                    run_id=run_id,
                    dataset_id=dataset_id,
                    task_id=task_id,
                    lock_digest=lock_digest,
                    status=status,
                    visibility="public" if public else "private",
                    blob_digest=blob_digest,
                    size=size,
                    archive=archive,
                    suite_run_id=suite_link,
                    replace=replace,
                    environment=job.get("environment") or None,
                    agent_label=job.get("agent_label") or None,
                    model_label=job.get("model_label") or None,
                    score=job.get("score"),
                )
            except RegistryError as exc:
                if allow_existing and (
                    exc.code == "conflict" or (exc.status == 409) or "already exists" in exc.message
                ):
                    return {
                        "ok": True,
                        "already_exists": True,
                        "run_id": run_id,
                        "dataset_id": dataset_id,
                        "blob_digest": blob_digest,
                        "size": size,
                        "visibility": "public" if public else "private",
                        "status": status,
                        "suite_run_id": suite_link,
                    }
                raise ConfigError(exc.code, exc.message, location="registry") from exc

        out: dict[str, Any] = {
            "ok": True,
            "already_exists": False,
            "run_id": info.get("run_id", run_id),
            "dataset_id": info.get("dataset_id", dataset_id),
            "blob_digest": info.get("blob_digest", blob_digest),
            "size": info.get("size", size),
            "visibility": info.get("visibility", "private"),
            "status": info.get("status", status),
        }
        if info.get("replaced"):
            out["replaced"] = True
        if suite_link:
            out["suite_run_id"] = info.get("suite_run_id", suite_link)
        elif info.get("suite_run_id"):
            out["suite_run_id"] = info["suite_run_id"]
        return out

    def get_attempt_result(
        self,
        run_id: str,
        *,
        out_dir: Path,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Download attempt bundle and extract under *out_dir*."""
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            meta = client.get_attempt(run_id)
            dest = out_dir.expanduser().resolve(strict=False)
            archive_path = dest / f"{run_id}.tar.gz"
            client.fetch_attempt_content(run_id, dest=archive_path)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc

        run_path = extract_attempt_archive(archive_path, dest)
        archive_path.unlink(missing_ok=True)
        return {
            "ok": True,
            "run_id": run_id,
            "dataset_id": meta.get("dataset_id"),
            "blob_digest": meta.get("blob_digest"),
            "out": str(run_path),
            "meta": meta,
        }

    def list_attempt_results(
        self,
        *,
        dataset_id: str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            items = client.list_attempts(dataset_id=dataset_id)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, "items": items, "count": len(items)}

    def upload_suite_result(
        self,
        dataset_root: Path,
        *,
        suite_run_id: str,
        public: bool = False,
        agent_label: str = "",
        model_label: str = "",
        with_attempts: bool = False,
        registry_url: str | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Pack ``.ageval/suite-runs/<id>`` and POST suite result to results store.

        When *with_attempts* is true, also upload each local ``.ageval/runs/<run_id>``
        referenced by suite ``task_refs`` (same visibility). Missing local run dirs
        fail closed before any network upload. Without *replace*, re-uploads of
        existing suite_run_id conflict (409); attempt re-uploads under
        ``--with-attempts`` remain idempotent (``already_exists``).
        """
        root = dataset_root.expanduser().resolve(strict=False)
        suite_dir = _resolve_suite_dir(root, suite_run_id)
        summary = _load_suite_summary(suite_dir)

        metrics, task_refs = _suite_metrics_and_refs(summary)
        try:
            pass_rate = float(metrics.get("pass_rate", 0.0))
            mean_score = float(metrics.get("mean_score", 0.0))
        except (TypeError, ValueError):
            pass_rate = 0.0
            mean_score = 0.0
        try:
            exit_code = int(summary.get("exit_code", 0))
        except (TypeError, ValueError):
            exit_code = 0

        dataset_id = str(summary.get("dataset_id") or "")
        dataset_version = str(summary.get("dataset_version") or "")
        if not dataset_id:
            try:
                man = load_dataset_manifest(root)
                dataset_id = man.dataset_id
                dataset_version = dataset_version or man.version
            except ConfigError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ConfigError("invalid_package", str(exc), location=str(root)) from exc

        run_ids = _run_ids_from_task_refs(task_refs) if with_attempts else []
        if with_attempts:
            missing: list[str] = []
            for rid in run_ids:
                try:
                    resolve_attempt_run_dir(root, rid)
                except ConfigError:
                    missing.append(rid)
            if missing:
                preview = ", ".join(missing[:8])
                more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
                raise ConfigError(
                    "invalid_package",
                    (
                        f"--with-attempts: missing local run dir(s) under "
                        f".ageval/runs/ for: {preview}{more}"
                    ),
                    location=str(default_runs_root(root)),
                )

        config_proj = _config_fields_from_summary(summary)
        overlay = config_proj.get("job_overlay")
        if isinstance(overlay, dict):
            from ageval.config.overlay_files import assert_job_overlay_files

            assert_job_overlay_files(root, overlay)

        archive_bytes, blob_digest, size = build_suite_archive(suite_dir, suite_run_id=suite_run_id)
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ageval-suite-") as tmp:
            archive = Path(tmp) / "suite.tar.gz"
            archive.write_bytes(archive_bytes)
            try:
                info = client.upload_suite(
                    suite_run_id=suite_run_id,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    visibility="public" if public else "private",
                    pass_rate=pass_rate,
                    mean_score=mean_score,
                    metrics=dict(metrics),
                    task_refs=list(task_refs),
                    agent_label=agent_label or str(summary.get("agent_label") or ""),
                    model_label=model_label or str(summary.get("model_label") or ""),
                    exit_code=exit_code,
                    blob_digest=blob_digest,
                    size=size,
                    archive=archive,
                    config_fingerprint=config_proj.get("config_fingerprint"),
                    config_homogeneous=config_proj.get("config_homogeneous"),
                    actors_summary=list(config_proj.get("actors_summary") or []),
                    job_overlay=config_proj.get("job_overlay")
                    if isinstance(config_proj.get("job_overlay"), dict)
                    else None,
                    plugins=list(config_proj.get("plugins") or [])
                    if isinstance(config_proj.get("plugins"), list)
                    else None,
                    replace=replace,
                )
            except RegistryError as exc:
                raise ConfigError(exc.code, exc.message, location="registry") from exc

        out: dict[str, Any] = {
            "ok": True,
            "suite_run_id": info.get("suite_run_id", suite_run_id),
            "dataset_id": info.get("dataset_id", dataset_id),
            "dataset_version": info.get("dataset_version", dataset_version),
            "pass_rate": info.get("pass_rate", pass_rate),
            "mean_score": info.get("mean_score", mean_score),
            "metrics": info.get("metrics", metrics),
            "task_refs": info.get("task_refs", task_refs),
            "blob_digest": info.get("blob_digest", blob_digest),
            "size": info.get("size", size),
            "visibility": info.get("visibility", "private"),
            "note": info.get("note", "per-task evaluator verdicts only; no suite-level PASS"),
        }
        if info.get("replaced"):
            out["replaced"] = True
        for key in (
            "config_fingerprint",
            "config_homogeneous",
            "actors_summary",
            "job_overlay",
            "plugins",
        ):
            if key in info:
                out[key] = info[key]
            elif key in config_proj:
                out[key] = config_proj[key]

        if with_attempts:
            attempt_uploads: list[dict[str, Any]] = []
            for rid in run_ids:
                # Same client/token path; re-use public + suite_run_id link.
                attempt_uploads.append(
                    self.upload_attempt_result(
                        root,
                        run_id=rid,
                        public=public,
                        suite_run_id=suite_run_id,
                        registry_url=registry_url,
                        # Under suite --replace, also overwrite attempt blobs; else
                        # keep idempotent skip of existing run_ids.
                        allow_existing=not replace,
                        replace=replace,
                    )
                )
            out["with_attempts"] = True
            out["attempts"] = attempt_uploads
            out["attempts_uploaded"] = sum(
                1 for a in attempt_uploads if a.get("ok") and not a.get("already_exists")
            )
            out["attempts_existing"] = sum(1 for a in attempt_uploads if a.get("already_exists"))
            out["attempts_total"] = len(attempt_uploads)
            # Suite POST response is pre-attempt; annotate refs for operator JSON.
            uploaded_ids = {
                str(a.get("run_id")) for a in attempt_uploads if a.get("ok") and a.get("run_id")
            }
            refs = out.get("task_refs")
            if isinstance(refs, list):
                enriched_refs: list[Any] = []
                for ref in refs:
                    if not isinstance(ref, dict):
                        enriched_refs.append(ref)
                        continue
                    item = dict(ref)
                    rid = str(item.get("run_id") or "").strip()
                    item["has_attempt_content"] = bool(rid and rid in uploaded_ids)
                    enriched_refs.append(item)
                out["task_refs"] = enriched_refs
        return out

    def append_suite_slot_result(
        self,
        dataset_root: Path,
        *,
        suite_run_id: str,
        task_id: str,
        run_id: str | None = None,
        attempt_index: int = 0,
        public: bool = False,
        with_attempts: bool = False,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Upload one new Attempt and PATCH that slot onto an existing suite.

        Does **not** call whole-row ``upload_suite --replace``. Old Attempt blobs
        stay. ``task_refs`` come from the local summary (current + previous[]).
        """
        root = dataset_root.expanduser().resolve(strict=False)
        suite_dir = _resolve_suite_dir(root, suite_run_id)
        summary = _load_suite_summary(suite_dir)
        metrics, task_refs = _suite_metrics_and_refs(summary)
        tid = task_id.strip()
        hit: dict[str, Any] | None = None
        for ref in task_refs:
            if str(ref.get("task_id") or "") == tid:
                hit = ref
                break
        if hit is None:
            raise ConfigError(
                "suite_replace_slot_missing",
                f"local suite has no task_ref for {tid}",
                location="--task",
            )
        current = (run_id or "").strip()
        if not current:
            for raw in summary.get("attempts") or []:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("task_id") or "") != tid:
                    continue
                idx = raw.get("attempt_index")
                if not isinstance(idx, int) or isinstance(idx, bool):
                    idx = 0
                if idx != attempt_index:
                    continue
                current = str(raw.get("run_id") or "").strip()
                break
            if not current:
                ids = hit.get("attempt_run_ids")
                if isinstance(ids, list) and 0 <= attempt_index < len(ids):
                    current = str(ids[attempt_index] or "").strip()
            if not current:
                current = str(hit.get("run_id") or "").strip()
        if not current:
            raise ConfigError(
                "suite_replace_slot_missing",
                f"no current run_id for {tid}[{attempt_index}]",
                location="--run",
            )
        current_ids = {str(hit.get("run_id") or "").strip()}
        extra = hit.get("attempt_run_ids")
        if isinstance(extra, list):
            current_ids.update(str(x).strip() for x in extra if x is not None)
        if current not in current_ids:
            raise ConfigError(
                "invalid_request",
                "--run must be the local current pointer for that slot",
                location="--run",
            )
        resolve_attempt_run_dir(root, current)

        upload_ids = [current]
        if with_attempts:
            prev = hit.get("previous")
            if isinstance(prev, list):
                for item in prev:
                    if not isinstance(item, dict):
                        continue
                    rid = str(item.get("run_id") or "").strip()
                    if rid and rid not in upload_ids:
                        try:
                            resolve_attempt_run_dir(root, rid)
                        except ConfigError:
                            continue
                        upload_ids.append(rid)

        attempt_uploads: list[dict[str, Any]] = []
        for rid in upload_ids:
            attempt_uploads.append(
                self.upload_attempt_result(
                    root,
                    run_id=rid,
                    public=public,
                    suite_run_id=suite_run_id,
                    registry_url=registry_url,
                    allow_existing=True,
                    replace=False,
                )
            )

        try:
            pass_rate = float(metrics.get("pass_rate", 0.0))
            mean_score = float(metrics.get("mean_score", 0.0))
        except (TypeError, ValueError):
            pass_rate = 0.0
            mean_score = 0.0
        try:
            exit_code = int(summary.get("exit_code", 0))
        except (TypeError, ValueError):
            exit_code = 0
        config_proj = _config_fields_from_summary(summary)
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            info = client.append_suite_slot(
                suite_run_id=suite_run_id,
                task_id=tid,
                run_id=current,
                attempt_index=attempt_index,
                task_refs=list(task_refs),
                metrics=dict(metrics),
                pass_rate=pass_rate,
                mean_score=mean_score,
                exit_code=exit_code,
                config_fingerprint=config_proj.get("config_fingerprint"),
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc

        out: dict[str, Any] = {
            "ok": True,
            "appended": True,
            "suite_run_id": info.get("suite_run_id", suite_run_id),
            "task_id": tid,
            "run_id": current,
            "attempt_index": attempt_index,
            "pass_rate": info.get("pass_rate", pass_rate),
            "mean_score": info.get("mean_score", mean_score),
            "metrics": info.get("metrics", metrics),
            "task_refs": info.get("task_refs", task_refs),
            "amended": True,
            "note": info.get("note", "per-task evaluator verdicts only; no suite-level PASS"),
            "attempts": attempt_uploads,
        }
        return out

    def get_suite_result(
        self,
        suite_run_id: str,
        *,
        out_dir: Path | None = None,
        local: Path | str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Fetch suite result meta (+ optional archive extract).

        When *local* is a Dataset root, read ``.ageval/suite-runs/<id>/summary.json``
        without contacting the registry.
        """
        if local is not None:
            root = resolve_dataset_root(local)
            suite_dir = _resolve_suite_dir(root, suite_run_id)
            summary = _load_suite_summary(suite_dir)
            item = _local_suite_item(summary, suite_dir=suite_dir)
            return {"ok": True, **item}

        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            meta = client.get_suite(suite_run_id)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc

        result: dict[str, Any] = {"ok": True, "source": "registry", **meta}
        if out_dir is not None:
            dest = out_dir.expanduser().resolve(strict=False)
            archive_path = dest / f"{suite_run_id}.tar.gz"
            try:
                client.fetch_suite_content(suite_run_id, dest=archive_path)
            except RegistryError as exc:
                raise ConfigError(exc.code, exc.message, location="registry") from exc
            suite_path = extract_suite_archive(archive_path, dest)
            archive_path.unlink(missing_ok=True)
            result["out"] = str(suite_path)
            # #59: materialize job_overlay as profiles.yaml next to extract when present.
            overlay = meta.get("job_overlay")
            if isinstance(overlay, dict) and overlay:
                from ageval.config.profiles import (
                    job_overlay_to_profiles_document,
                    write_profiles_yaml,
                )

                profiles_path = suite_path / "profiles.from-suite.yaml"
                write_profiles_yaml(profiles_path, job_overlay_to_profiles_document(overlay))
                result["profiles_path"] = str(profiles_path)
        return result

    def export_suite_profiles(
        self,
        suite_run_id: str,
        *,
        out: Path,
        local: Path | str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Export secret-free job_overlay as a re-runnable ``profiles.yaml`` (#59).

        Source: local suite summary or Registry suite meta. Never writes secret values.
        """
        from ageval.config.profiles import job_overlay_to_profiles_document, write_profiles_yaml

        meta = self.get_suite_result(suite_run_id, local=local, registry_url=registry_url)
        overlay = meta.get("job_overlay")
        if not isinstance(overlay, dict) or not overlay:
            raise ConfigError(
                "missing_reference",
                "suite has no job_overlay (re-run suite after #59 or upload with binding)",
                location=suite_run_id,
            )
        document = job_overlay_to_profiles_document(overlay)
        dest = out.expanduser().resolve(strict=False)
        write_profiles_yaml(dest, document)
        return {
            "ok": True,
            "suite_run_id": suite_run_id,
            "profiles_path": str(dest),
            "job_overlay": overlay,
            "source": meta.get("source") or ("local" if local else "registry"),
            "note": "re-run with: ageval run <dataset> --profiles "
            + str(dest)
            + " (fill .env locators locally; secrets never in overlay)",
        }

    def list_suite_results(
        self,
        *,
        dataset_id: str | None = None,
        local: Path | str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """List suite results from registry, or local ``.ageval/suite-runs/`` when *local* set."""
        if local is not None:
            root = resolve_dataset_root(local)
            suite_root = root / ".ageval" / "suite-runs"
            items: list[dict[str, Any]] = []
            if suite_root.is_dir():
                for child in sorted(suite_root.iterdir(), key=lambda p: p.name, reverse=True):
                    if not child.is_dir():
                        continue
                    summary_path = child / "summary.json"
                    if not summary_path.is_file():
                        continue
                    try:
                        summary = _load_suite_summary(child)
                    except ConfigError:
                        continue
                    item = _local_suite_item(summary, suite_dir=child)
                    if dataset_id and item.get("dataset_id") != dataset_id:
                        continue
                    items.append(item)
            return {"ok": True, "items": items, "count": len(items), "source": "local"}

        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            items = client.list_suites(dataset_id=dataset_id)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, "items": items, "count": len(items), "source": "registry"}

    def attach_suite_agent(
        self,
        *,
        suite_run_id: str,
        agent: str,
        role: str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Attach a published ``org/name@version`` onto a Registry suite overlay."""
        sid = suite_run_id.strip()
        spec = agent.strip()
        if not sid:
            raise ConfigError("invalid_request", "suite-run is required", location="--suite-run")
        if not spec:
            raise ConfigError("invalid_request", "agent is required", location="--agent")
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            payload = client.attach_suite_agent(
                suite_run_id=sid,
                agent=spec,
                role=role.strip() if isinstance(role, str) and role.strip() else None,
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, **payload}

    def apply_request(
        self,
        *,
        kind: str,
        suite_run_id: str,
        agent: str | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        kind_s = kind.strip()
        sid = suite_run_id.strip()
        if kind_s not in {"leaderboard_list", "agent_appearance"}:
            raise ConfigError("invalid_request", "unknown request kind", location="--kind")
        if not sid:
            raise ConfigError("invalid_request", "suite-run is required", location="--suite-run")
        if kind_s == "agent_appearance" and not (agent or "").strip():
            raise ConfigError("invalid_request", "agent is required", location="--agent")
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            payload = client.apply_request(
                kind=kind_s,
                suite_run_id=sid,
                agent=agent.strip() if isinstance(agent, str) and agent.strip() else None,
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, **payload}

    def list_inbox(self, *, registry_url: str | None = None) -> dict[str, Any]:
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            items = client.list_inbox()
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, "items": items, "count": len(items)}

    def decide_requests(
        self,
        *,
        ids: list[str],
        action: str,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        action_s = action.strip()
        if action_s not in {"approve", "reject"}:
            raise ConfigError(
                "invalid_request", "action must be approve or reject", location="--action"
            )
        want = [i.strip() for i in ids if i.strip()]
        if not want:
            raise ConfigError("invalid_request", "id is required", location="--id")
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            payload = client.decide_requests(ids=want, action=action_s)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {"ok": True, **payload}

    def share_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        share_orgs: list[str] | None = None,
        share_users: list[str] | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Share a private attempt/suite result with orgs and/or users (owner only)."""
        if result_kind not in {"attempt", "suite"}:
            raise ConfigError(
                "invalid_request",
                "result_kind must be attempt or suite",
                location="registry",
            )
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        created: list[dict[str, Any]] = []
        try:
            for org in share_orgs or []:
                created.append(
                    client.share_result(
                        result_kind=result_kind,
                        result_id=result_id,
                        target_type="org",
                        target_id=org,
                    )
                )
            for user in share_users or []:
                created.append(
                    client.share_result(
                        result_kind=result_kind,
                        result_id=result_id,
                        target_type="user",
                        target_id=user,
                    )
                )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {
            "ok": True,
            "result_kind": result_kind,
            "result_id": result_id,
            "shares": created,
            "count": len(created),
        }

    def unshare_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        share_orgs: list[str] | None = None,
        share_users: list[str] | None = None,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Revoke private result share grants (owner only)."""
        if result_kind not in {"attempt", "suite"}:
            raise ConfigError(
                "invalid_request",
                "result_kind must be attempt or suite",
                location="registry",
            )
        if not share_orgs and not share_users:
            raise ConfigError(
                "invalid_request",
                "provide at least one share_org or share_user to unshare",
                location="registry",
            )
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        removed: list[dict[str, Any]] = []
        try:
            for org in share_orgs or []:
                removed.append(
                    client.unshare_result(
                        result_kind=result_kind,
                        result_id=result_id,
                        target_type="org",
                        target_id=org,
                    )
                )
            for user in share_users or []:
                removed.append(
                    client.unshare_result(
                        result_kind=result_kind,
                        result_id=result_id,
                        target_type="user",
                        target_id=user,
                    )
                )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {
            "ok": True,
            "result_kind": result_kind,
            "result_id": result_id,
            "unshared": removed,
            "count": len(removed),
        }

    def delete_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        with_attempts: bool = False,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Delete an attempt or suite result owned by the current principal."""
        if result_kind not in {"attempt", "suite"}:
            raise ConfigError(
                "invalid_request",
                "result_kind must be attempt or suite",
                location="registry",
            )
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            if result_kind == "attempt":
                if with_attempts:
                    raise ConfigError(
                        "invalid_request",
                        "--with-attempts is only valid for suite results",
                        location="registry",
                    )
                return client.delete_attempt(result_id)
            return client.delete_suite(result_id, with_attempts=with_attempts)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc

    def set_result_visibility(
        self,
        *,
        result_kind: str,
        result_id: str,
        visibility: str,
        registry_url: str | None = None,
    ) -> dict[str, Any]:
        """Set attempt/suite visibility after create (owner only)."""
        if result_kind not in {"attempt", "suite"}:
            raise ConfigError(
                "invalid_request",
                "result_kind must be attempt or suite",
                location="registry",
            )
        if visibility not in {"public", "private"}:
            raise ConfigError(
                "invalid_request",
                "visibility must be public or private",
                location="registry",
            )
        client = self._client_factory(
            registry_url=registry_url, require_token=True, accept_results_url=True
        )
        try:
            if result_kind == "attempt":
                return client.set_attempt_visibility(result_id, visibility=visibility)
            return client.set_suite_visibility(result_id, visibility=visibility)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
