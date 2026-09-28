import { useNavigate } from "react-router-dom";

import { LeaderboardWaffle as SharedWaffle } from "@ageval/shared/components/leaderboard-waffle";
import { encodeDatasetId, type SuiteRow } from "@/lib/api";
import type { WaffleTrial } from "@/lib/leaderboard-charts";

export { WaffleLegend } from "@ageval/shared/components/leaderboard-waffle";

/** Hub routes stay here. The chart itself is shared with Viewer. */
export function LeaderboardWaffle({
  datasetId,
  suites,
  onOpenSuite,
  emptyTitle,
  emptyBody,
  showCaption,
}: {
  suites: SuiteRow[];
  datasetId: string;
  onOpenSuite?: (suiteRunId: string | null) => void;
  emptyTitle?: string;
  emptyBody?: string;
  showCaption?: boolean;
}) {
  const navigate = useNavigate();

  function onOpenTrial(
    suite: { suite_run_id: string },
    trial: WaffleTrial,
  ) {
    if (trial.hasAttempt && trial.runId) {
      navigate(
        `/datasets/${encodeDatasetId(datasetId)}/tasks/${encodeURIComponent(trial.taskId)}/attempts/${encodeURIComponent(trial.runId)}`,
      );
      return;
    }
    onOpenSuite?.(suite.suite_run_id);
  }

  return (
    <SharedWaffle
      suites={suites}
      onOpenSuite={onOpenSuite}
      onOpenTrial={onOpenTrial}
      emptyTitle={emptyTitle}
      emptyBody={emptyBody}
      showCaption={showCaption}
    />
  );
}
