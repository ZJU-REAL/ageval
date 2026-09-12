import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { LoadingState } from "@/components/empty-state";
import { CatalogHead } from "@/components/page-head";
import { CommandStrip } from "@/components/command-strip";
import { ActorsTable } from "@/components/trial/actors-table";
import { EvidenceTabs } from "@/components/trial/evidence-tabs";
import { OutcomeStrip } from "@/components/trial/outcome-strip";
import { PhaseTimingBar } from "@/components/trial/phase-timing-bar";
import { TrialHeader } from "@/components/trial/trial-header";
import { useAttemptEvidence } from "@/hooks/use-attempt-evidence";
import { ResultOwnerOps } from "@/components/result-owner-ops";
import {
  decodeDatasetId,
  decodeFileContent,
  getAttempt,
  getAttemptFile,
  listSuites,
  type AttemptMeta,
} from "@/lib/api";
import { toArchivePath } from "@/lib/attempt-evidence";
import { getGithubUser, getToken } from "@/lib/auth";
import { INTERNAL_LINK_CLASS } from "@/lib/links";

async function readAttemptStartedAt(
  runId: string,
  token: string | null,
): Promise<string | null> {
  try {
    const file = await getAttemptFile(
      runId,
      toArchivePath("summary.json", runId),
      token,
    );
    const text = decodeFileContent(file);
    if (!text) return null;
    const data = JSON.parse(text) as {
      phase_timing?: { started_at?: unknown };
    };
    const raw = data.phase_timing?.started_at;
    if (typeof raw === "string" && raw.trim()) return raw.trim();
  } catch {
    return null;
  }
  return null;
}

/**
 * Hub Jobs deep-link: uploaded Attempt evidence with viewer-parity IA
 * (outcome, actors, Trajectory / Agent / Verifier / Lock / Runtime tabs).
 *
 * Package Dataset ``shared/`` is browsed on Task Files / Dataset Shared tab —
 * not inside Attempt evidence (Local | Shared does not apply here).
 */
export function AttemptEvidencePage() {
  const { datasetId: rawId, taskId: rawTask, runId: rawRun } = useParams();
  const datasetId = decodeDatasetId(rawId || "");
  const taskId = decodeURIComponent(rawTask || "");
  const runId = decodeURIComponent(rawRun || "");
  const token = getToken();
  const navigate = useNavigate();
  const [slotCurrentRunId, setSlotCurrentRunId] = useState<string | null>(null);
  const [slotCurrentStartedAt, setSlotCurrentStartedAt] = useState<string | null>(
    null,
  );
  const [slotPrevious, setSlotPrevious] = useState<
    Array<{
      run_id?: string | null;
      status?: string | null;
      started_at?: string | null;
      replaced_at?: string | null;
    }>
  >([]);
  const [attemptMeta, setAttemptMeta] = useState<AttemptMeta | null>(null);

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
  } = useAttemptEvidence(runId, taskId, token);

  useEffect(() => {
    if (!runId) {
      setAttemptMeta(null);
      return;
    }
    let cancelled = false;
    getAttempt(runId, token)
      .then((meta) => {
        if (!cancelled) setAttemptMeta(meta);
      })
      .catch(() => {
        if (!cancelled) setAttemptMeta(null);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, token]);

  useEffect(() => {
    let cancelled = false;
    if (!datasetId || !taskId || !runId) return;
    listSuites(datasetId, token)
      .then(async (suites) => {
        if (cancelled) return;
        for (const suite of suites) {
          const hit = (suite.task_refs || []).find((ref) => ref.task_id === taskId);
          if (!hit) continue;
          const prev = hit.previous || [];
          const ids = [
            hit.run_id,
            ...(hit.attempt_run_ids || []),
            ...prev.map((item) => item.run_id),
          ];
          if (!ids.includes(runId)) continue;
          const current = hit.run_id ?? null;
          const [currentAt, ...prevTimes] = await Promise.all([
            current ? readAttemptStartedAt(current, token) : Promise.resolve(null),
            ...prev.map((item) =>
              item.run_id
                ? item.started_at || readAttemptStartedAt(item.run_id, token)
                : Promise.resolve(null),
            ),
          ]);
          if (cancelled) return;
          setSlotCurrentRunId(current);
          setSlotCurrentStartedAt(currentAt);
          setSlotPrevious(
            prev.map((item, i) => ({
              ...item,
              started_at: item.started_at || prevTimes[i] || null,
            })),
          );
          return;
        }
        setSlotCurrentRunId(null);
        setSlotCurrentStartedAt(null);
        setSlotPrevious([]);
      })
      .catch(() => {
        if (!cancelled) {
          setSlotCurrentRunId(null);
          setSlotCurrentStartedAt(null);
          setSlotPrevious([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, taskId, runId, token]);

  const jobsHref = `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}?tab=jobs`;
  const attemptHref = (id: string) =>
    `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}/attempts/${encodeURIComponent(id)}`;

  return (
    <>
      <CatalogHead
        title="Datasets"
        crumbs={[
          { label: "Datasets", href: "/datasets" },
          {
            label: datasetId,
            href: `/datasets/${encodeURIComponent(datasetId)}`,
          },
          { label: taskId, href: jobsHref },
          { label: runId, href: null },
        ]}
      />
      <div className="space-y-5">
        <TrialHeader
          runId={runId}
          taskId={taskId}
          trial={trial}
          slotCurrentRunId={slotCurrentRunId}
          slotCurrentStartedAt={slotCurrentStartedAt}
          slotPrevious={slotPrevious}
          onSlotSelect={(id) => navigate(attemptHref(id))}
          actions={
            attemptMeta &&
            (attemptMeta.uploaded_by || "").toLowerCase() ===
              (getGithubUser() || "").toLowerCase() ? (
              <ResultOwnerOps
                kind="attempt"
                resultId={runId}
                visibility={attemptMeta.visibility}
                canManage
                token={token}
                onVisibility={(next) =>
                  setAttemptMeta((prev) =>
                    prev ? { ...prev, visibility: next } : prev,
                  )
                }
                onDeleted={() => navigate(jobsHref)}
              />
            ) : null
          }
        />

        {runCommand ? <CommandStrip command={runCommand} /> : null}

        {loading && <LoadingState label="Loading attempt evidence" />}

        {error ? (
          <div className="blob-panel p-6 space-y-3">
            <p className="text-sm text-error font-mono">{error}</p>
            <p className="text-sm text-mute">
              Full evidence may not be uploaded yet. Upload with{" "}
              <code className="font-mono">ageval results upload</code> or{" "}
              <code className="font-mono">upload-suite --with-attempts</code>,
              then return from{" "}
              <Link
                to={jobsHref}
                className={INTERNAL_LINK_CLASS}
              >
                Jobs
              </Link>
              .
            </p>
            <CommandStrip
              command={`ageval results upload <dataset-root> --run ${runId}`}
            />
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

        {!loading && !error && !trial ? (
          <p className="text-sm text-mute">No trial meta for this run.</p>
        ) : null}
      </div>
    </>
  );
}
