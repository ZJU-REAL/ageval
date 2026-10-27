"""Prepare a checkpoint fork before any environment starts.

A fork mints a new Attempt, copies the activity prefix and selected
checkpoint, and switches only the solver model. It never attaches the
parent environment.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ageval.attempt.recover import new_nonce
from ageval.config.errors import ConfigError
from ageval.evidence.activity import ActivityLog, ActivityRecord
from ageval.evidence.fork_cuts import FORK_CONTINUATION_KINDS, list_fork_cuts
from ageval.evidence.locators import default_runs_root
from ageval.evidence.store import ACTIVITY_LOG_REL, CHECKPOINTS_DIR_REL

_MODEL_LEAVES = frozenset({"id", "api", "timeout", "watchdog", "reasoning/effort"})
_IGNORE_LOCK_PATHS = frozenset({"/digest", "/resolution", "/source", "/eval_digest"})
_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd")


class ForkRejection(ConfigError):
    """A fork that must stop before an environment starts."""


@dataclass(frozen=True)
class ForkRequest:
    source_attempt_id: str
    checkpoint_seq: int
    model: str


@dataclass(frozen=True)
class ForkPlan:
    source_dir: Path
    checkpoint_seq: int
    solver_role: str
    executor_kind: str
    source_model: str
    continuation_model: str
    source_digest: str
    context_conversion: str
    shared_prefix_usage: dict[str, float]
    changes: tuple[dict[str, str], ...]

    def provenance(self, *, child_digest: str, verified: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": "ageval.fork/1",
            "parent_attempt_id": self.source_dir.name,
            "checkpoint_seq": self.checkpoint_seq,
            "source_locked_config_digest": self.source_digest,
            "child_locked_config_digest": child_digest,
            "source_model": self.source_model,
            "continuation_model": self.continuation_model,
            "continuation_model_verified": verified,
            "context_conversion": self.context_conversion,
            "executor_kind": self.executor_kind,
            "changes": [dict(item) for item in self.changes],
        }
        if self.shared_prefix_usage:
            payload["shared_prefix_usage"] = dict(self.shared_prefix_usage)
        return payload


def prepare_fork(
    dataset: Path,
    request: ForkRequest,
    *,
    child_lock: dict[str, object],
) -> ForkPlan:
    """Validate the cut and the lock diff. Does not create the child Attempt."""
    source = _source_dir(dataset, request.source_attempt_id)
    listing = list_fork_cuts(source, attempt_id=source.name)
    if listing.error:
        raise ForkRejection(listing.error, listing.message or listing.error, location="--fork")
    cut = next((item for item in listing.cuts if item.seq == request.checkpoint_seq), None)
    if cut is None or not cut.forkable:
        reason = cut.reason if cut is not None and cut.reason else "not_a_completed_cut"
        raise ForkRejection(
            reason,
            f"checkpoint {request.checkpoint_seq} cannot start a fork",
            location="--checkpoint",
        )
    log = ActivityLog.open(source / ACTIVITY_LOG_REL)
    session = _session_at(log, request.checkpoint_seq)
    role = str(session.payload.get("profile_id") or "")
    executor = str(session.payload.get("executor_kind") or "")
    if not role or executor not in FORK_CONTINUATION_KINDS:
        raise ForkRejection(
            "continuation_unsupported",
            f"executor {executor or 'unknown'} cannot continue a fork",
            location="--fork",
        )
    source_lock = _read_json(source / "lock.json")
    source_model = _model_id(source_lock, role)
    if not source_model:
        raise ForkRejection(
            "fork_model_unbound",
            f"source lock has no model.id for {role}",
            location="--fork",
        )
    child_model = _model_id(child_lock, role)
    if child_model != request.model:
        raise ForkRejection(
            "fork_model_unbound",
            f"locked continuation model is {child_model or 'missing'}, not {request.model}",
            location="--model",
        )
    changes = _lock_changes(source_lock, child_lock, role)
    unexpected = [item for item in changes if not _allowed_model_change(item["path"], role)]
    if unexpected:
        shown = ", ".join(item["path"] for item in unexpected[:5])
        raise ForkRejection(
            "fork_config_rejected",
            f"fork may change only the solver model; also changed {shown}",
            location="--fork",
        )
    model_changes = tuple(item for item in changes if _allowed_model_change(item["path"], role))
    if not any(item["path"].endswith("/model/id") for item in model_changes):
        model_changes = (
            {
                "role": role,
                "path": f"/agent_profiles/{role}/model/id",
                "from": source_model,
                "to": request.model,
            },
            *model_changes,
        )
    return ForkPlan(
        source_dir=source,
        checkpoint_seq=request.checkpoint_seq,
        solver_role=role,
        executor_kind=executor,
        source_model=source_model,
        continuation_model=request.model,
        source_digest=str(source_lock.get("digest") or ""),
        context_conversion=_context_conversion(log, request.checkpoint_seq),
        shared_prefix_usage=_shared_usage(log, request.checkpoint_seq),
        changes=model_changes,
    )


def model_override(role: str, model: str) -> dict[str, str]:
    return {f"/agent_profiles/{role}/model/id": model}


def source_profiles_file(dataset: Path, attempt_id: str) -> Path:
    """Write the source job overlay as a profiles file for the child lock.

    The operator does not pass ``--profiles``. The file keeps the source
    harness and environment so the child lock can change only the model.
    """
    source = _source_dir(dataset, attempt_id)
    lock = _read_json(source / "lock.json")
    overlay = lock.get("job_overlay")
    if not isinstance(overlay, dict):
        raise ForkRejection(
            "fork_source_invalid",
            "source lock has no job_overlay",
            location="--fork",
        )
    from ageval.config.profiles import job_overlay_to_profiles_document

    document = job_overlay_to_profiles_document(overlay)
    fd, name = tempfile.mkstemp(prefix="ageval-fork-profiles-", suffix=".yaml")
    path = Path(name)
    import os

    os.close(fd)
    import yaml

    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def solver_role_from_source(dataset: Path, attempt_id: str, seq: int) -> str:
    """Role id needed to lock the child. Fails before lock when the cut is unsafe."""
    source = _source_dir(dataset, attempt_id)
    listing = list_fork_cuts(source, attempt_id=source.name)
    if listing.error:
        raise ForkRejection(listing.error, listing.message or listing.error, location="--fork")
    cut = next((item for item in listing.cuts if item.seq == seq), None)
    if cut is None or not cut.forkable:
        reason = cut.reason if cut is not None and cut.reason else "not_a_completed_cut"
        raise ForkRejection(
            reason,
            f"checkpoint {seq} cannot start a fork",
            location="--checkpoint",
        )
    session = _session_at(ActivityLog.open(source / ACTIVITY_LOG_REL), seq)
    role = str(session.payload.get("profile_id") or "")
    if not role:
        raise ForkRejection(
            "continuation_unsupported", "fork session has no profile", location="--fork"
        )
    return role


def copy_fork_prefix(
    source: Path,
    dest_attempt: Path,
    *,
    seq: int,
    run_id: str,
    trial_id: str,
    attempt_id: str,
    digest: str,
) -> ActivityLog:
    """Copy the activity prefix and selected checkpoint blobs into the child."""
    src_log = ActivityLog.open(source / ACTIVITY_LOG_REL)
    dest_log = ActivityLog.open(dest_attempt / ACTIVITY_LOG_REL)
    nonce = new_nonce()
    for record in src_log.records:
        if record.seq > seq:
            break
        payload = dict(record.payload)
        if record.kind == "attempt" and record.seq == 1:
            payload["run_id"] = run_id
            payload["trial_id"] = trial_id
            payload["attempt_id"] = attempt_id
            payload["locked_config_digest"] = digest
            payload["environment_nonce"] = nonce
            payload["environment_handle"] = None
        else:
            payload["inherited"] = True
        dest_log.append(
            request_id=record.request_id,
            kind=record.kind,
            status=record.status,
            payload=payload,
        )
    _copy_checkpoints(source, dest_attempt, seq)
    return dest_log


def _source_dir(dataset: Path, attempt_id: str) -> Path:
    name = attempt_id.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ForkRejection(
            "unknown_run", "attempt id must be a single directory name", location="--fork"
        )
    root = default_runs_root(dataset) / name
    if not root.is_dir():
        raise ForkRejection("unknown_run", "attempt directory was not found", location="--fork")
    return root


def _session_at(log: ActivityLog, seq: int) -> ActivityRecord:
    found = [
        record
        for record in log.records
        if record.kind == "session" and record.status == "completed" and record.seq <= seq
    ]
    if len(found) != 1:
        raise ForkRejection(
            "multi_session" if len(found) > 1 else "state_not_restorable",
            "fork needs exactly one session in the prefix",
            location="--checkpoint",
        )
    return found[0]


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ForkRejection("fork_source_invalid", "source lock.json is missing", location="--fork")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ForkRejection(
            "fork_source_invalid", "source lock.json is not readable", location="--fork"
        ) from exc
    if not isinstance(data, dict):
        raise ForkRejection(
            "fork_source_invalid", "source lock.json is not an object", location="--fork"
        )
    return data


def _model_id(lock: dict[str, object], role: str) -> str:
    overlay = lock.get("job_overlay")
    profiles = overlay.get("agent_profiles") if isinstance(overlay, dict) else None
    row = profiles.get(role) if isinstance(profiles, dict) else None
    if not isinstance(row, dict):
        return ""
    model = row.get("model")
    if isinstance(model, str):
        return model
    if isinstance(model, dict):
        raw = model.get("id")
        return raw if isinstance(raw, str) else ""
    return ""


def _lock_changes(
    source: dict[str, object],
    child: dict[str, object],
    role: str,
) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    _walk(source, child, "", role, changes)
    return changes


def _walk(
    source: object,
    child: object,
    path: str,
    role: str,
    changes: list[dict[str, str]],
) -> None:
    if path in _IGNORE_LOCK_PATHS:
        return
    if isinstance(source, dict) and isinstance(child, dict):
        keys = sorted(set(source) | set(child))
        for key in keys:
            _walk(source.get(key), child.get(key), f"{path}/{key}", role, changes)
        return
    if isinstance(source, list) and isinstance(child, list):
        if source != child:
            changes.append(
                {"role": role, "path": path or "/", "from": _short(source), "to": _short(child)}
            )
        return
    if source != child:
        changes.append(
            {"role": role, "path": path or "/", "from": _short(source), "to": _short(child)}
        )


def _allowed_model_change(path: str, role: str) -> bool:
    marker = f"/agent_profiles/{role}/model/"
    if marker not in path:
        return False
    leaf = path.split(marker, 1)[1]
    return leaf in _MODEL_LEAVES


def _context_conversion(log: ActivityLog, seq: int) -> str:
    compacted = any(
        record.kind == "compaction" and record.status == "completed" and record.seq <= seq
        for record in log.records
    )
    if compacted:
        return "activity_prefix_compaction"
    return "activity_prefix"


def _shared_usage(log: ActivityLog, seq: int) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in log.records:
        if record.seq > seq or record.status != "completed":
            continue
        if record.kind not in {"model_turn", "compaction"}:
            continue
        usage = record.payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in _USAGE_KEYS:
            raw = usage.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                continue
            totals[key] = totals.get(key, 0.0) + float(raw)
    return totals


def _copy_checkpoints(source: Path, dest: Path, seq: int) -> None:
    src_root = source / CHECKPOINTS_DIR_REL
    if not src_root.is_dir():
        return
    for path in sorted(src_root.glob("seq_*.json")):
        stem = path.stem.removeprefix("seq_")
        if not stem.isdigit() or int(stem) > seq:
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        dest_manifest = dest / CHECKPOINTS_DIR_REL / path.name
        dest_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest_manifest)
        entries = manifest.get("entries") if isinstance(manifest, dict) else None
        if not isinstance(entries, dict):
            continue
        for meta in entries.values():
            if not isinstance(meta, dict):
                continue
            digest = meta.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                continue
            blob = src_root / "blobs" / digest[:2] / digest
            if not blob.is_file():
                continue
            target = dest / CHECKPOINTS_DIR_REL / "blobs" / digest[:2] / digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                shutil.copyfile(blob, target)


def _short(value: object) -> str:
    if isinstance(value, str):
        return value
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) > 180:
        return text[:177] + "..."
    return text
