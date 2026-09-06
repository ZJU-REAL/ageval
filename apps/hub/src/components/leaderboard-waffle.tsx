import { useNavigate } from "react-router-dom";

import { HoverTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import { encodeDatasetId, type SuiteRow } from "@/lib/api";
import {
  trialsForRef,
  waffleTaskIds,
  type TrialKind,
  type WaffleTrial,
} from "@/lib/leaderboard-charts";
import { cn, displayLabelsFromOverlay } from "@/lib/utils";

const KIND_CLASS: Record<TrialKind, string> = {
  pass: "bg-ink",
  fail: "bg-canvas-soft-2 border border-hairline",
  error: "bg-error",
};

function EmptyBoard({
  emptyTitle,
  emptyBody,
}: {
  emptyTitle?: string;
  emptyBody?: string;
}) {
  return (
    <div className="blob-panel space-y-3 p-6">
      <p className="text-sm font-medium text-ink">
        {emptyTitle || "No Leaderboard rows yet"}
      </p>
      <p className="text-sm text-mute">
        {emptyBody ||
          "Public board lists complete, release-bound suites after Dataset org listing approval. Incomplete or draft-bound runs stay on Internal and the task Jobs list. Upload with ageval results upload-suite, then request listing. Metrics are observational, not a suite-level PASS."}
      </p>
    </div>
  );
}

export function LeaderboardWaffle({
  suites,
  datasetId,
  onOpenSuite,
  emptyTitle,
  emptyBody,
}: {
  suites: SuiteRow[];
  datasetId: string;
  onOpenSuite?: (suiteRunId: string | null) => void;
  emptyTitle?: string;
  emptyBody?: string;
}) {
  const navigate = useNavigate();
  const tasks = waffleTaskIds(suites);
  const ranked = [...suites].sort((a, b) => {
    const av = a.pass_rate ?? -1;
    const bv = b.pass_rate ?? -1;
    if (av !== bv) return bv - av;
    return a.suite_run_id.localeCompare(b.suite_run_id);
  });

  if (suites.length === 0) {
    return <EmptyBoard emptyTitle={emptyTitle} emptyBody={emptyBody} />;
  }

  function openTrial(suite: SuiteRow, trial: WaffleTrial) {
    if (trial.hasAttempt && trial.runId) {
      navigate(
        `/datasets/${encodeDatasetId(datasetId)}/tasks/${encodeURIComponent(trial.taskId)}/attempts/${encodeURIComponent(trial.runId)}`,
      );
      return;
    }
    onOpenSuite?.(suite.suite_run_id);
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-mute">
        Each square is one trial. Click a square with uploaded Attempt evidence
        to open that job. Metrics are observational, not a suite PASS.
      </p>
      <div className="blob-panel max-h-[min(70vh,40rem)] overflow-auto">
        <div
          className="grid w-max min-w-full"
          style={{
            gridTemplateColumns: `12rem repeat(${ranked.length}, minmax(4.75rem, 1fr))`,
          }}
        >
          <div className="sticky top-0 left-0 z-20 min-h-20 border-b border-r border-hairline bg-canvas" />
          {ranked.map((suite) => {
            const labels = displayLabelsFromOverlay(suite.job_overlay);
            const model = labels.model || suite.model_label || "—";
            const harness = labels.agent || suite.agent_label || "—";
            return (
              <HoverTip
                key={suite.suite_run_id}
                content={
                  <span>
                    <span className="block font-medium">
                      {harness} / {model}
                    </span>
                    <span className="text-mute">Click to open suite run</span>
                  </span>
                }
              >
                <button
                  type="button"
                  className={cn(
                    "sticky top-0 z-10 flex min-h-20 min-w-[4.75rem] flex-col justify-end gap-0.5 border-b border-r border-hairline bg-canvas px-2 py-2 text-left text-sm hover:bg-canvas-soft",
                  )}
                  aria-label={`${harness} ${model}. Click to open suite run`}
                  onClick={() => onOpenSuite?.(suite.suite_run_id)}
                >
                  <ModelLabel value={model} />
                  <span className="text-mute">{harness}</span>
                </button>
              </HoverTip>
            );
          })}
          {tasks.map((taskId) => (
            <WaffleTaskRow
              key={taskId}
              taskId={taskId}
              suites={ranked}
              onOpenTrial={openTrial}
            />
          ))}
        </div>
      </div>
      <p className="flex flex-wrap items-center gap-3 text-xs text-body">
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[2px] bg-ink" />
          pass
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[2px] border border-hairline bg-canvas-soft-2" />
          fail
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[2px] bg-error" />
          error
        </span>
      </p>
    </div>
  );
}

function WaffleTaskRow({
  taskId,
  suites,
  onOpenTrial,
}: {
  taskId: string;
  suites: SuiteRow[];
  onOpenTrial: (suite: SuiteRow, trial: WaffleTrial) => void;
}) {
  return (
    <>
      <div className="sticky left-0 z-[5] flex items-center border-b border-r border-hairline bg-canvas px-2.5 py-2 text-sm">
        {taskId}
      </div>
      {suites.map((suite) => {
        const ref = (suite.task_refs || []).find(
          (row) => (row.task_id || "").trim() === taskId,
        );
        const trials = ref ? trialsForRef(suite.suite_run_id, ref) : [];
        return (
          <div
            key={`${suite.suite_run_id}:${taskId}`}
            className="flex items-center gap-0.5 border-b border-r border-hairline px-2 py-2"
          >
            {trials.length === 0 ? (
              <span className="text-xs text-mute">—</span>
            ) : (
              trials.map((trial) => {
                const labels = displayLabelsFromOverlay(suite.job_overlay);
                const hint = trial.hasAttempt
                  ? "Click to open job"
                  : "Click to open suite run";
                return (
                  <HoverTip
                    key={trial.key}
                    content={
                      <span>
                        <span className="block font-medium">{taskId}</span>
                        <span className="block">
                          {labels.agent || suite.agent_label} /{" "}
                          {labels.model || suite.model_label}
                        </span>
                        <span className="block">
                          trial {trial.attemptIndex + 1} · {trial.kind}
                        </span>
                        <span className="text-mute">{hint}</span>
                      </span>
                    }
                  >
                    <button
                      type="button"
                      className={cn(
                        "h-2.5 w-2.5 shrink-0 rounded-[2px]",
                        KIND_CLASS[trial.kind],
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                      )}
                      aria-label={`${taskId} trial ${trial.attemptIndex + 1} ${trial.kind}. ${hint}`}
                      onClick={() => onOpenTrial(suite, trial)}
                    />
                  </HoverTip>
                );
              })
            )}
          </div>
        );
      })}
    </>
  );
}
