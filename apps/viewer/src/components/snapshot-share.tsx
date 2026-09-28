import { Check, Copy, Share2 } from "lucide-react";
import { useEffect, useState } from "react";

import { ThinkingLogo } from "@ageval/shared/components/thinking-logo";
import { Button, SegmentedControl } from "@ageval/shared/components/ui/button";
import { ConfirmDialog, Modal } from "@ageval/shared/components/ui/confirm-dialog";
import { toast } from "@ageval/shared/components/ui/toast";
import { cn } from "@ageval/shared/lib/utils";
import {
  createSnapshotShare,
  fetchSnapshotShare,
  revokeSnapshotShare,
  type SnapshotShareState,
} from "@/lib/api";

const SUITE_BODY =
  "Share uploads this suite to the registry. Anyone with the link can view that snapshot. The suite stays private and is not listed on the leaderboard.";
const SUITE_LIVE_BODY =
  "Share uploads this suite and keeps one link. The link updates when a job finishes. The suite stays private and is not listed on the leaderboard.";
const JOB_BODY =
  "Share uploads this job to the registry. Anyone with the link can view that snapshot. It is not added to the catalog or the leaderboard.";
const LIVE_LINK =
  "Anyone with this link can view the suite. It updates when a job finishes.";
const SNAPSHOT_STEPS = [
  "Packing this snapshot",
  "Stripping secrets from the copy",
  "Uploading to the registry",
  "Waiting for the link",
] as const;
const LIVE_STEPS = [
  "Packing this suite",
  "Stripping secrets from the copy",
  "Uploading the first snapshot",
  "Binding the live link",
] as const;
const UNSHARE_STEPS = ["Revoking this link", "Removing it from the registry"] as const;

function ShareProgress({ lines }: { lines: readonly string[] }) {
  const [index, setIndex] = useState(0);
  const [shown, setShown] = useState(true);

  useEffect(() => {
    let fade = 0;
    const tick = window.setInterval(() => {
      setShown(false);
      fade = window.setTimeout(() => {
        setIndex((current) => (current + 1) % lines.length);
        setShown(true);
      }, 320);
    }, 2600);
    return () => {
      window.clearInterval(tick);
      window.clearTimeout(fade);
    };
  }, [lines]);

  return (
    <div className="flex items-center justify-start gap-3" role="status" aria-live="polite">
      <ThinkingLogo size={36} />
      <p
        className={cn(
          "text-sm text-mute motion-safe:transition-opacity motion-safe:duration-300",
          shown ? "opacity-100" : "motion-safe:opacity-0",
        )}
      >
        {lines[index]}
      </p>
    </div>
  );
}

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
  const [mode, setMode] = useState<"static" | "live">("static");
  const suite = !runId;
  const body = runId ? JOB_BODY : mode === "live" ? SUITE_LIVE_BODY : SUITE_BODY;
  const shared = Boolean(state?.shared && state.url);
  const liveLink = state?.mode === "live";

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
      const live = suite && mode === "live";
      setState(await createSnapshotShare(jobId, runId, live));
      toast(live ? "Live link created" : "Snapshot link created");
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
      toast("Share link removed");
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
          setMode("static");
          setOpen(true);
        }}
      >
        <Share2 className="h-4 w-4" />
      </Button>
      {shared && state?.url ? (
        <Modal
          open={open}
          title="Shared link"
          description={liveLink ? LIVE_LINK : "Anyone with this link can view the snapshot."}
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
            {busy ? <ShareProgress lines={UNSHARE_STEPS} /> : null}
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
          keepConfirmLabel
          busyStatus={<ShareProgress lines={suite && mode === "live" ? LIVE_STEPS : SNAPSHOT_STEPS} />}
          className={suite ? "max-w-lg" : undefined}
          onCancel={() => {
            if (!busy) setOpen(false);
          }}
          onConfirm={() => void share()}
        >
          {suite ? (
            <SegmentedControl<"static" | "live">
              label="Share mode"
              items={[
                { id: "static", label: "Snapshot" },
                { id: "live", label: "Live" },
              ]}
              selected={(id) => id === mode}
              onSelect={(id) => {
                if (!busy) setMode(id);
              }}
            />
          ) : null}
        </ConfirmDialog>
      )}
    </>
  );
}
