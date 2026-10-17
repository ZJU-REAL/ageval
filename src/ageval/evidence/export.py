"""Versioned trajectory export — re-redact sealed Attempt evidence (Spec 16).

Export is a read-only copy; never mutates source evidence or evaluation score.
Refuses unsealed or secret-residual invocations (fail closed).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.evidence.locators import portable_run_locator
from ageval.evidence.redaction import (
    RedactionError,
    assert_clean,
    redact_value,
    scan_for_secrets,
)
from ageval.evidence.store import is_sealed_invocation, parse_jsonl_recover

EXPORT_SCHEMA = "ageval.trajectory.export/1"


@dataclass(frozen=True, slots=True)
class ExportResult:
    ok: bool
    export_path: str
    invocation_count: int
    error: str | None = None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def export_trajectory(
    evidence_root: Path,
    dest_dir: Path,
    *,
    extra_sentinels: list[str] | None = None,
) -> ExportResult:
    """Copy sealed invocation trees into a versioned export package.

    Fail closed when any invocation is unsealed (status running / missing meta)
    or when residual secrets remain after redaction.
    """
    evidence_root = evidence_root.resolve()
    if not evidence_root.is_dir():
        return ExportResult(False, "", 0, error="evidence_root_missing")

    inv_src = evidence_root / "agent" / "invocations"
    inv_dirs = sorted(p for p in inv_src.iterdir() if p.is_dir()) if inv_src.is_dir() else []
    traj_src = evidence_root / "trajectory.jsonl"

    if traj_src.is_file():
        hits = scan_for_secrets(
            traj_src.read_text(encoding="utf-8", errors="replace"),
            extra_sentinels=extra_sentinels or (),
        )
        if hits:
            return ExportResult(False, "", 0, error="secret_residual:trajectory.jsonl")

    # Preflight: remaining invocation dirs must be sealed terminals.
    # Slim trees keep empty invocation dirs (count) without metadata.json;
    # layer C jsonl is enough to replay those.
    for inv in inv_dirs:
        if traj_src.is_file() and not (inv / "metadata.json").is_file():
            continue
        if not is_sealed_invocation(inv):
            return ExportResult(
                False,
                "",
                0,
                error=f"unsealed_invocation:{inv.name}",
            )
        # Residual secret scan on source files before export.
        for name in ("metadata.json", "request.json", "final-response.json", "events.jsonl"):
            p = inv / name
            if not p.is_file():
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
            hits = scan_for_secrets(raw, extra_sentinels=extra_sentinels or ())
            if hits:
                return ExportResult(
                    False,
                    "",
                    0,
                    error=f"secret_residual:{inv.name}:{name}",
                )

    dest_dir = dest_dir.resolve()
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    # Write to temp then rename for atomic publish.
    staging = dest_dir.with_name(dest_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        manifest_invocations: list[dict[str, Any]] = []
        if traj_src.is_file():
            dest_traj = staging / "trajectory.jsonl"
            dest_traj.write_text(
                traj_src.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        for inv in inv_dirs:
            if traj_src.is_file() and not (inv / "metadata.json").is_file():
                continue
            out_inv = staging / "invocations" / inv.name
            out_inv.mkdir(parents=True)
            source_digests: dict[str, str] = {}
            for name in ("metadata.json", "request.json", "final-response.json"):
                src = inv / name
                if not src.is_file():
                    continue
                source_digests[name] = _sha256_file(src)
                try:
                    data = json.loads(src.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return ExportResult(False, "", 0, error=f"tampered_json:{inv.name}:{name}")
                cleaned = redact_value(data, extra_sentinels=extra_sentinels or ())
                try:
                    assert_clean(cleaned, extra_sentinels=extra_sentinels or ())
                except RedactionError:
                    return ExportResult(
                        False, "", 0, error=f"secret_residual_after_redact:{inv.name}:{name}"
                    )
                (out_inv / name).write_text(
                    json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            events_path = inv / "events.jsonl"
            if events_path.is_file():
                source_digests["events.jsonl"] = _sha256_file(events_path)
                rows = parse_jsonl_recover(events_path)
                with (out_inv / "events.jsonl").open("w", encoding="utf-8") as fh:
                    for row in rows:
                        cleaned = redact_value(row, extra_sentinels=extra_sentinels or ())
                        assert_clean(cleaned, extra_sentinels=extra_sentinels or ())
                        fh.write(json.dumps(cleaned, sort_keys=True, separators=(",", ":")) + "\n")
            meta_path = out_inv / "metadata.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            manifest_invocations.append(
                {
                    "dir": inv.name,
                    "status": meta.get("status"),
                    "source": str(inv.relative_to(evidence_root)),
                    "source_digests": source_digests,
                    "sealed": True,
                }
            )

        effects = parse_jsonl_recover(evidence_root / "effects.jsonl")
        with (staging / "effects.jsonl").open("w", encoding="utf-8") as fh:
            for row in effects:
                cleaned = redact_value(row, extra_sentinels=extra_sentinels or ())
                assert_clean(cleaned, extra_sentinels=extra_sentinels or ())
                fh.write(json.dumps(cleaned, sort_keys=True, separators=(",", ":")) + "\n")

        manifest = {
            "schema": EXPORT_SCHEMA,
            # Portable under Dataset root when layout is …/.ageval/runs/<id> (#70).
            "source_evidence": portable_run_locator(evidence_root),
            "invocation_count": len(manifest_invocations),
            "invocations": manifest_invocations,
            "trajectory": "trajectory.jsonl" if traj_src.is_file() else None,
            "note": (
                "export is a re-redacted sealed copy; layer C trajectory.jsonl "
                "is the Hub-facing replay; score authority remains evaluator binding"
            ),
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # Atomic publish
        staging.rename(dest_dir)
    except OSError as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return ExportResult(False, "", 0, error=f"export_failed:{type(exc).__name__}")

    return ExportResult(
        ok=True,
        export_path=str(dest_dir),
        invocation_count=len(manifest_invocations),
    )
