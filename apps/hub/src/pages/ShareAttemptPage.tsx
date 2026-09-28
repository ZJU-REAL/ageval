import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { LoadingState } from "@ageval/shared/components/empty-state";
import { CommandStrip } from "@ageval/shared/components/command-strip";
import { ActorsTable } from "@ageval/shared/components/trial/actors-table";
import { EvidenceTabs } from "@ageval/shared/components/trial/evidence-tabs";
import { OutcomeStrip } from "@ageval/shared/components/trial/outcome-strip";
import { PhaseTimingBar } from "@ageval/shared/components/trial/phase-timing-bar";
import { TrialHeader } from "@ageval/shared/components/trial/trial-header";

import { CatalogHead } from "@/components/page-head";
import { useAttemptEvidence } from "@/hooks/use-attempt-evidence";
import {
  getSnapshotAttempt,
  getSnapshotAttemptFile,
  getSnapshotShare,
  listSnapshotAttemptFiles,
  RegistryHttpError,
  type SnapshotShare,
} from "@/lib/api";
import { harnessHref, modelCatalogHref } from "@/lib/links";
import { INTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";

/**
 * Attempt evidence already uploaded for this snapshot. Read-only; no catalog
 * upload and no stream of a job that is still running.
 */
export function ShareAttemptPage() {
  const { token: rawToken = "", runId: rawRun = "" } = useParams();
  const token = decodeURIComponent(rawToken);
  const runId = decodeURIComponent(rawRun);
  const navigate = useNavigate();
  const [share, setShare] = useState<SnapshotShare | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getSnapshotShare(token)
      .then((row) => {
        if (!cancelled) setShare(row);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setShare(null);
        if (err instanceof RegistryHttpError) {
          setShareError(
            err.status === 404 ? "This snapshot link is not available." : err.message,
          );
        } else {
          setShareError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const taskRef = useMemo(() => {
    for (const ref of share?.task_refs || []) {
      const ids = [
        ref.run_id,
        ...(ref.attempt_run_ids || []),
        ...(ref.previous || []).map((item) => item.run_id),
      ];
      if (ids.includes(runId)) return ref;
    }
    return null;
  }, [share, runId]);
  const taskId = (taskRef?.task_id || "").trim();

  const source = useMemo(
    () => ({
      getMeta: () => getSnapshotAttempt(token, runId),
      listFiles: () => listSnapshotAttemptFiles(token, runId),
      getFile: (archivePath: string) =>
        getSnapshotAttemptFile(token, runId, archivePath),
    }),
    [token, runId],
  );
  const {
    trial,
    result,
    runCommand,
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
    tree,
    treeGroups,
    treeLoading,
    selectedPath,
    setSelectedPath,
    fileContent,
    fileNote,
    fileLoading,
  } = useAttemptEvidence(runId, taskId, null, source);

  const suiteHref = `/s/${encodeURIComponent(token)}`;
  const attemptHref = (id: string) =>
    `/s/${encodeURIComponent(token)}/attempts/${encodeURIComponent(id)}`;
  const datasetId = share?.dataset_id || "Snapshot";

  return (
    <>
      <CatalogHead
        title="Snapshot"
        crumbs={[
          { label: datasetId, href: suiteHref },
          { label: taskId || runId, href: null },
          { label: runId, href: null },
        ]}
      />
      <div className="space-y-5">
        <TrialHeader
          runId={runId}
          taskId={taskId}
          trial={trial}
          slotCurrentRunId={taskRef?.run_id || null}
          slotPrevious={(taskRef?.previous || []).map((item) => ({
            run_id: item.run_id,
            status: item.status,
            started_at: item.started_at,
          }))}
          onSlotSelect={(id) => navigate(attemptHref(id))}
        />
        {runCommand ? <CommandStrip command={runCommand} /> : null}
        {shareError ? (
          <p className="text-sm text-error font-mono">{shareError}</p>
        ) : null}
        {loading ? <LoadingState label="Loading attempt evidence" /> : null}
        {error ? (
          <div className="blob-panel p-6 space-y-3">
            <p className="text-sm text-error font-mono">{error}</p>
            <p className="text-sm text-mute">
              This attempt is not in the snapshot.{" "}
              <Link to={suiteHref} className={INTERNAL_LINK_CLASS}>
                Back to the snapshot
              </Link>
              .
            </p>
          </div>
        ) : null}
        {!loading && !error && trial ? (
          <>
            <OutcomeStrip trial={trial} />
            <PhaseTimingBar
              phaseTiming={trial.phase_timing}
              tokenTiming={trial.token_timing}
            />
            {trial.actors && trial.actors.length > 0 ? (
              <ActorsTable
                actors={trial.actors}
                harnessTo={harnessHref}
                modelTo={modelCatalogHref}
              />
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
              loadScript={async (packagePath) => ({
                content: null,
                note: packagePath,
              })}
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
            />
          </>
        ) : null}
        {!loading && !error && !trial && !shareError ? (
          <p className="text-sm text-mute">No trial meta for this run.</p>
        ) : null}
      </div>
    </>
  );
}
