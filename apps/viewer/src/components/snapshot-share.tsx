import { Check, Copy, Share2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import { ConfirmDialog, Modal } from "@ageval/shared/components/ui/confirm-dialog";
import { toast } from "@ageval/shared/components/ui/toast";
import {
  createSnapshotShare,
  fetchSnapshotShare,
  revokeSnapshotShare,
  type SnapshotShareState,
} from "@/lib/api";

const SUITE_BODY =
  "Share uploads this suite to the registry. Anyone with the link can view that snapshot. The suite stays private and is not listed on the leaderboard.";
const JOB_BODY =
  "Share uploads this job to the registry. Anyone with the link can view that snapshot. It is not added to the catalog or the leaderboard.";

/**
 * Create or revoke a snapshot link for the opened suite or one job.
 * The explanation and the link stay in the dialog, not on the page.
 */
export function SnapshotShareControl({
  jobId,
  runId,
}: {
  jobId: string;
  runId?: string;
}) {
  const [state, setState] = useState<SnapshotShareState | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const body = runId ? JOB_BODY : SUITE_BODY;
  const shared = Boolean(state?.shared && state.url);

  useEffect(() => {
    let cancelled = false;
    fetchSnapshotShare(jobId, runId)
      .then((row) => {
        if (!cancelled) setState(row);
      })
      .catch(() => {
        if (!cancelled) setState({ ok: true, shared: false });
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, runId]);

  function fail(err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    toast(message.trim() || "Share failed", { tone: "error" });
  }

  async function share() {
    setBusy(true);
    try {
      setCopied(false);
      setState(await createSnapshotShare(jobId, runId));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function unshare() {
    setBusy(true);
    try {
      const row = await revokeSnapshotShare(jobId, runId);
      setState({ ...row, shared: false, url: undefined });
      setOpen(false);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    const url = state?.url;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch (err) {
      fail(err);
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={busy}
        aria-label="Share"
        onClick={() => {
          setCopied(false);
          setOpen(true);
        }}
      >
        <Share2 className="h-4 w-4" />
      </Button>
      {shared && state?.url ? (
        <Modal
          open={open}
          title="Shared link"
          description="Anyone with this link can view the snapshot."
          className="max-w-lg"
          onClose={() => setOpen(false)}
        >
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1 overflow-x-auto overscroll-x-contain rounded-[10px] border border-hairline bg-code-bg px-3 py-2">
                <p className="whitespace-nowrap font-mono text-xs text-ink">{state.url}</p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="shrink-0"
                aria-label={copied ? "Copied" : "Copy"}
                onClick={() => void copyLink()}
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void unshare()}
              >
                Unshare
              </Button>
            </div>
          </div>
        </Modal>
      ) : (
        <ConfirmDialog
          open={open}
          title={runId ? "Share this job" : "Share this suite"}
          description={body}
          confirmLabel="Share"
          confirmVariant="default"
          busy={busy}
          onCancel={() => {
            if (!busy) setOpen(false);
          }}
          onConfirm={() => void share()}
        />
      )}
    </>
  );
}
