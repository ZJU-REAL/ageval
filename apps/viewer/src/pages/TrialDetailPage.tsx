import { Link, useNavigate, useParams } from "react-router-dom";

import { BreadcrumbNav } from "@ageval/shared/components/breadcrumb";
import { CommandStrip } from "@ageval/shared/components/command-strip";
import { LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import { SnapshotShareControl } from "@/components/snapshot-share";
import { ActorsTable } from "@ageval/shared/components/trial/actors-table";
import { EvidenceTabs } from "@ageval/shared/components/trial/evidence-tabs";
import { OutcomeStrip } from "@ageval/shared/components/trial/outcome-strip";
import { PhaseTimingBar } from "@ageval/shared/components/trial/phase-timing-bar";
import { TrialHeader } from "@ageval/shared/components/trial/trial-header";
import { useTrialDetail } from "@/hooks/use-trial-detail";
import type { Trial } from "@/lib/api";
import { jobPath, jobsHome, taskPath, trialPath } from "@/lib/routes";
import { INTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";

export function TrialDetailPage() {
  const { datasetKey = "", jobId = "", taskId = "", runId = "" } = useParams();
  const navigate = useNavigate();
  const detail = useTrialDetail(datasetKey, jobId, taskId, runId);

  function goSibling(id: string | null) {
    if (!id) return;
    navigate(trialPath(datasetKey, jobId, taskId, id));
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
                  { label: "Jobs", href: jobsHome(datasetKey) },
                  { label: taskId, href: null },
                  { label: runId, href: null },
                ]
              : [
                  { label: "Jobs", href: jobsHome(datasetKey) },
                  { label: jobId, href: jobPath(datasetKey, jobId) },
                  {
                    label: taskId,
                    href: siblingRunIds.length > 1 ? taskPath(datasetKey, jobId, taskId) : null,
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
          actions={<SnapshotShareControl jobId={jobId} runId={runId} />}
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

            {trial.analysis && trial.analysis.length > 0 ? (
              <AnalysisSection reports={trial.analysis} />
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
                <Link to="/" className={INTERNAL_LINK_CLASS}>
                  ← Back to jobs
                </Link>
              ) : siblingRunIds.length > 1 ? (
                <Link
                  to={taskPath(datasetKey, jobId, taskId)}
                  className={INTERNAL_LINK_CLASS}
                >
                  ← Back to trials
                </Link>
              ) : (
                <Link to={jobPath(datasetKey, jobId)} className={INTERNAL_LINK_CLASS}>
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

type AnalysisReport = NonNullable<Trial["analysis"]>[number];

function AnalysisSection({ reports }: { reports: AnalysisReport[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-ink">Analysis</h2>
      {reports.map((item) => (
        <article key={item.analyzer} className="blob-panel space-y-2 p-4">
          <h3 className="text-sm font-medium text-ink">{item.analyzer}</h3>
          <AnalysisBody item={item} />
        </article>
      ))}
    </section>
  );
}

function AnalysisBody({ item }: { item: AnalysisReport }) {
  if (item.note || !item.report) {
    return <p className="text-sm text-mute">{item.note || "report.json could not be read"}</p>;
  }
  const report = item.report;
  if (isRecord(report.metrics)) {
    return <StatsBody metrics={report.metrics} />;
  }
  if (Array.isArray(report.findings)) {
    return <ReviewBody findings={report.findings} />;
  }
  if ("stage1" in report || "is_hack" in report) {
    return <HackBody report={report} />;
  }
  return (
    <pre className="overflow-x-auto font-mono text-xs text-body">
      {JSON.stringify(report, null, 2)}
    </pre>
  );
}

function StatsBody({ metrics }: { metrics: Record<string, unknown> }) {
  const rows: Array<[string, unknown]> = [
    ["invoke_count", metrics.invoke_count],
    ["tool_call_count", metrics.tool_call_count],
    ["tool_failure_count", metrics.tool_failure_count],
    ["tool_failure_rate", metrics.tool_failure_rate],
    ["upstream_stall_count", metrics.upstream_stall_count],
  ];
  const gaps = Array.isArray(metrics.gaps) ? metrics.gaps.filter((item) => typeof item === "string") : [];
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-mute">{label}</dt>
            <dd className="font-mono text-ink tabular-nums">{metricText(value)}</dd>
          </div>
        ))}
      </dl>
      {gaps.length > 0 ? (
        <p className="text-sm text-mute">gaps {gaps.join(", ")}</p>
      ) : null}
    </div>
  );
}

function HackBody({ report }: { report: Record<string, unknown> }) {
  const stage1 = isRecord(report.stage1) ? report.stage1 : null;
  const count = stage1 && typeof stage1.suspect_count === "number" ? stage1.suspect_count : null;
  return (
    <div className="space-y-1 text-sm text-body">
      {"is_hack" in report ? (
        <p>
          is_hack <span className="font-mono text-ink">{String(report.is_hack)}</span>
        </p>
      ) : (
        <p className="text-mute">is_hack was not decided</p>
      )}
      {typeof report.category === "string" ? <p>category {report.category}</p> : null}
      {typeof report.decided_by === "string" ? <p>decided by {report.decided_by}</p> : null}
      {count !== null ? (
        <p>
          suspects <span className="font-mono text-ink tabular-nums">{count}</span>
        </p>
      ) : null}
      {typeof report.evidence_quote === "string" && report.evidence_quote ? (
        <p className="font-mono text-xs text-mute">{report.evidence_quote}</p>
      ) : null}
    </div>
  );
}

function ReviewBody({ findings }: { findings: unknown[] }) {
  return (
    <div className="space-y-3">
      {findings.map((finding, index) => {
        if (!isRecord(finding)) {
          return null;
        }
        return (
          <div key={`${String(finding.rubric)}-${index}`} className="space-y-1">
            <p className="text-sm text-ink">
              {typeof finding.rubric === "string" ? finding.rubric : "finding"}
              {typeof finding.judgment === "string" ? ` · ${finding.judgment}` : ""}
            </p>
            {typeof finding.summary === "string" ? (
              <p className="text-sm text-body">{finding.summary}</p>
            ) : null}
            {typeof finding.evidence_quote === "string" && finding.evidence_quote ? (
              <p className="font-mono text-xs text-mute">{finding.evidence_quote}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function metricText(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number" || typeof value === "string" || typeof value === "boolean") {
    return String(value);
  }
  return "null";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
