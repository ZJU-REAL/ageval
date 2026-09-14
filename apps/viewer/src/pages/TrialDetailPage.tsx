import { Link, useNavigate, useParams } from "react-router-dom";

import { BreadcrumbNav } from "@ageval/shared/components/breadcrumb";
import { CommandStrip } from "@ageval/shared/components/command-strip";
import { LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import { ActorsTable } from "@ageval/shared/components/trial/actors-table";
import { EvidenceTabs } from "@ageval/shared/components/trial/evidence-tabs";
import { OutcomeStrip } from "@ageval/shared/components/trial/outcome-strip";
import { PhaseTimingBar } from "@ageval/shared/components/trial/phase-timing-bar";
import { TrialHeader } from "@ageval/shared/components/trial/trial-header";
import { useTrialDetail } from "@/hooks/use-trial-detail";
import { jobPath, taskPath, trialPath } from "@/lib/routes";

export function TrialDetailPage() {
  const { jobId = "", taskId = "", runId = "" } = useParams();
  const navigate = useNavigate();
  const detail = useTrialDetail(jobId, taskId, runId);

  function goSibling(id: string | null) {
    if (!id) return;
    navigate(trialPath(jobId, taskId, id));
  }

  const {
    trial,
    job,
    siblingRunIds,
    result,
    runCommand,
    prevId,
    nextId,
    slotCurrentRunId,
    slotCurrentStartedAt,
    slotPrevious,
    error,
    loading,
    activeTab,
    setActiveTab,
    availableTabs,
    steps,
    trajNote,
    trajLoading,
    observationSteps,
    obsNote,
    obsLoading,
    loadScript,
    tree,
    treeGroups,
    treeLoading,
    selectedPath,
    setSelectedPath,
    fileContent,
    fileNote,
    fileLoading,
  } = detail;

  return (
    <Shell>
      <div className="space-y-5">
        <BreadcrumbNav
          items={
            job?.source_kind === "single"
              ? [
                  { label: "Jobs", href: "/" },
                  { label: taskId, href: null },
                  { label: runId, href: null },
                ]
              : [
                  { label: "Jobs", href: "/" },
                  { label: jobId, href: jobPath(jobId) },
                  {
                    label: taskId,
                    href: siblingRunIds.length > 1 ? taskPath(jobId, taskId) : null,
                  },
                  { label: runId, href: null },
                ]
          }
        />

        <TrialHeader
          runId={runId}
          taskId={taskId}
          trial={trial}
          prevId={prevId}
          nextId={nextId}
          onSibling={goSibling}
          documentTitle
          slotCurrentRunId={slotCurrentRunId}
          slotCurrentStartedAt={slotCurrentStartedAt}
          slotPrevious={slotPrevious}
          onSlotSelect={goSibling}
        />

        {runCommand ? <CommandStrip command={runCommand} /> : null}

        {loading && <LoadingState label="Loading trial" />}
        {error && <p className="text-sm text-error">{error}</p>}

        {!loading && !error && trial && (
          <>
            <OutcomeStrip trial={trial} />

            <PhaseTimingBar
              phaseTiming={trial.phase_timing}
              tokenTiming={trial.token_timing}
            />

            {trial.actors && trial.actors.length > 0 ? (
              <ActorsTable actors={trial.actors} />
            ) : null}

            <EvidenceTabs
              availableTabs={availableTabs}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              trajLoading={trajLoading}
              steps={steps}
              trajNote={trajNote}
              observationSteps={observationSteps}
              obsLoading={obsLoading}
              obsNote={obsNote}
              taskId={taskId}
              loadScript={loadScript}
              result={result}
              actors={trial.actors || []}
              tree={tree}
              treeLoading={treeLoading}
              selectedPath={selectedPath}
              onSelectPath={setSelectedPath}
              fileContent={fileContent}
              fileLoading={fileLoading}
              fileNote={fileNote}
              treeGroups={treeGroups}
              emptyNote="No evidence files found for this run under the Dataset root."
            />

            <p className="text-xs text-mute">
              {job?.source_kind === "single" ? (
                <Link to="/" className="text-link hover:text-link-deep">
                  ← Back to jobs
                </Link>
              ) : siblingRunIds.length > 1 ? (
                <Link
                  to={taskPath(jobId, taskId)}
                  className="text-link hover:text-link-deep"
                >
                  ← Back to trials
                </Link>
              ) : (
                <Link to={jobPath(jobId)} className="text-link hover:text-link-deep">
                  ← Back to job
                </Link>
              )}
            </p>
          </>
        )}
      </div>
    </Shell>
  );
}
