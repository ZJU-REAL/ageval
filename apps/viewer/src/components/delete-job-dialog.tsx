import { useEffect, useState } from "react";

import { ConfirmDialog } from "@ageval/shared/components/ui/confirm-dialog";
import { toast } from "@ageval/shared/components/ui/toast";
import {
  deleteJob,
  fetchDeletePreview,
  type DeletePreview,
  type Job,
} from "@/lib/api";
import { jobDisplayName } from "@/lib/routes";
import { formatBytes } from "@ageval/shared/lib/utils";

type PreviewRow = {
  job: Job;
  preview: DeletePreview | null;
  errorCode: string | null;
  error: string | null;
  warningCode: string | null;
};

function inProgressCopy(count: number, bulk: boolean): string {
  if (!bulk || count === 1) return "You can delete it anyway.";
  return `You can delete all ${count} anyway.`;
}

function blockedCopy(rows: PreviewRow[], bulk: boolean): string | null {
  if (rows.length === 0) return null;
  const codes = new Set(rows.map((r) => r.errorCode).filter(Boolean));
  const one = !bulk || rows.length === 1;
  if (codes.size === 1 && codes.has("job_inner_attempt")) {
    return one
      ? "This attempt still belongs to a suite. Delete the suite instead."
      : "These attempts still belong to a suite. Delete the suite instead.";
  }
  if (codes.size === 1 && codes.has("job_claimed_elsewhere")) {
    return one
      ? "Another suite still claims an attempt here."
      : "Another suite still claims some of these attempts.";
  }
  if (codes.size === 1 && codes.has("job_in_progress")) {
    return one
      ? "This attempt isn't finished yet."
      : "Some of these attempts aren't finished yet.";
  }
  if (one) return rows[0].error || "Can't delete this job.";
  return `${rows.length} jobs can't be deleted.`;
}

type Props = {
  jobs: Job[];
  onClose: () => void;
  onDeleted: (jobIds: string[]) => void;
};

export function DeleteJobDialog({ jobs, onClose, onDeleted }: Props) {
  const [rows, setRows] = useState<PreviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const ids = jobs.map((j) => j.job_id).join(",");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all(
      jobs.map(async (job) => {
        try {
          const preview = await fetchDeletePreview(job.job_id);
          return {
            job,
            preview,
            errorCode: preview.can_delete ? null : preview.error?.code || null,
            error: preview.can_delete
              ? null
              : preview.error?.message || "cannot delete",
            warningCode: preview.warning?.code || null,
          };
        } catch (e) {
          return {
            job,
            preview: null,
            errorCode: null,
            error: e instanceof Error ? e.message : String(e),
            warningCode: null,
          };
        }
      }),
    )
      .then((next) => {
        if (!cancelled) {
          setRows(next);
          setError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ids, jobs]);

  const ready = rows.filter((r) => r.preview?.can_delete && r.preview.confirm_token);
  const blocked = rows.filter((r) => r.error);
  const running = rows.filter((r) => r.warningCode === "job_in_progress");
  const bulk = jobs.length > 1;
  const runningHint = running.length ? inProgressCopy(running.length, bulk) : null;
  const blockedHint = blockedCopy(blocked, bulk);
  const paths = ready.flatMap((r) => r.preview?.paths || []);
  const bytes = ready.reduce((sum, r) => sum + (r.preview?.bytes || 0), 0);
  const cascade = ready.reduce((sum, r) => sum + (r.preview?.cascade_run_ids.length || 0), 0);
  const singleKind = rows[0]?.preview?.kind || jobs[0]?.source_kind || "job";

  async function onConfirm() {
    if (ready.length === 0) return;
    setBusy(true);
    const deleted: string[] = [];
    const failures: string[] = [];
    for (const row of ready) {
      const token = row.preview?.confirm_token;
      if (!token) continue;
      try {
        await deleteJob(row.job.job_id, token);
        deleted.push(row.job.job_id);
      } catch (e) {
        failures.push(e instanceof Error ? e.message : String(e));
      }
    }
    if (deleted.length && !failures.length) {
      toast(deleted.length === 1 ? "Job deleted" : `${deleted.length} jobs deleted`);
      onDeleted(deleted);
      return;
    }
    if (deleted.length) {
      toast(
        deleted.length === 1 ? "Job deleted" : `${deleted.length} jobs deleted`,
        { tone: "error" },
      );
      onDeleted(deleted);
    }
    setError(failures.join(" · ") || "nothing can be deleted");
    setBusy(false);
  }

  const consequence = bulk
    ? "This removes each selected Job. Suite rows also delete every Attempt they reference."
    : singleKind === "suite"
      ? "This removes the suite tree and every Attempt it references. Those Attempts will not come back as singles."
      : "This removes this Attempt directory.";

  return (
    <ConfirmDialog
      open
      className="max-w-lg"
      title={bulk ? `Delete ${jobs.length} jobs` : `Delete ${singleKind} job`}
      description={
        <>
          <span className="block text-xs truncate">
            {bulk
              ? jobs.map((j) => jobDisplayName(j)).join(", ")
              : jobDisplayName(jobs[0])}
          </span>
          <span className="mt-2 block">{consequence}</span>
        </>
      }
      confirmLabel={bulk ? `Delete ${ready.length}` : "Delete"}
      busy={busy}
      confirmDisabled={loading || ready.length === 0}
      error={error}
      onCancel={onClose}
      onConfirm={() => void onConfirm()}
    >
      <div className="space-y-3 text-sm">
        {loading && <p className="text-mute">Loading preview...</p>}
        {runningHint ? (
          <p className="text-xs text-body">
            <span className="text-mute">Still running or canceling. </span>
            {runningHint}
          </p>
        ) : null}
        {blockedHint ? <p className="text-sm text-body">{blockedHint}</p> : null}
        {paths.length > 0 ? (
          <>
            <ul className="max-h-48 overflow-auto rounded-[8px] border border-hairline bg-canvas-soft divide-y divide-hairline">
              {paths.map((row) => (
                <li
                  key={`${row.locator}-${row.run_id || ""}`}
                  className="flex items-start justify-between gap-3 px-2.5 py-1.5"
                >
                  <span className="text-xs break-all">
                    {row.locator}
                    {!row.exists ? (
                      <span className="text-mute"> (missing)</span>
                    ) : null}
                  </span>
                  <span className="tabular text-xs text-mute shrink-0">
                    {formatBytes(row.bytes)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-mute tabular">
              {formatBytes(bytes)} total
              {cascade
                ? ` · ${cascade} attempt${cascade === 1 ? "" : "s"}`
                : ""}
            </p>
          </>
        ) : null}
      </div>
    </ConfirmDialog>
  );
}
