import { CircleAlert, CircleCheck, CircleX } from "lucide-react";
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
import { cn } from "@ageval/shared/lib/utils";

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
        <AnalysisArticle key={item.analyzer} item={item} />
      ))}
    </section>
  );
}

function AnalysisArticle({ item }: { item: AnalysisReport }) {
  const kind = analysisKind(item);
  if (kind === "hack") {
    return (
      <article className="blob-panel overflow-hidden">
        <HackBody report={item.report ?? {}} />
      </article>
    );
  }
  if (kind === "review") {
    return (
      <article className="blob-panel overflow-hidden">
        <ReviewBody findings={Array.isArray(item.report?.findings) ? item.report.findings : []} />
      </article>
    );
  }
  return (
    <article className="blob-panel space-y-2 p-4">
      <h3 className="text-sm font-medium text-ink">{analyzerTitle(item.analyzer)}</h3>
      <AnalysisBody item={item} />
    </article>
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
  return (
    <pre className="overflow-x-auto font-mono text-xs text-body">
      {JSON.stringify(report, null, 2)}
    </pre>
  );
}

function analyzerTitle(name: string): string {
  if (name === "stats") return "Stats";
  if (name === "hack") return "Hack";
  if (name === "review") return "Review";
  return name;
}

function analysisKind(item: AnalysisReport): "stats" | "hack" | "review" | "other" {
  if (item.note || !item.report) return "other";
  const report = item.report;
  if (isRecord(report.metrics)) return "stats";
  if (Array.isArray(report.findings)) return "review";
  if ("stage1" in report || "is_hack" in report) return "hack";
  return "other";
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

const HACK_CATEGORY_LABEL: Record<string, string> = {
  mutate_tests: "Mutate tests",
  read_gold: "Read gold",
  write_result: "Write result",
  outbound_download: "Outbound download",
  other_llm: "Other model",
};

const DECIDED_BY_LABEL: Record<string, string> = {
  stage1: "Stage 1",
  stage2: "Stage 2",
};

const RUBRIC_LABEL: Record<string, string> = {
  reward_hacking: "Reward hacking",
  task_specification: "Task specification",
};

const JUDGMENT_LABEL: Record<string, string> = {
  not_observed: "Not observed",
  suspected: "Suspected",
  confirmed: "Confirmed",
  met: "Met",
  missed: "Missed",
  unclear: "Unclear",
};

type MarkTone = "ok" | "bad" | "warn" | "none";

function HackBody({ report }: { report: Record<string, unknown> }) {
  const decided = hackDecision(report);
  const stage1 = isRecord(report.stage1) ? report.stage1 : null;
  const count = stage1 && typeof stage1.suspect_count === "number" ? stage1.suspect_count : null;
  const category = typeof report.category === "string" ? report.category.trim() : "";
  const decidedBy = typeof report.decided_by === "string" ? report.decided_by.trim() : "";
  const quote = typeof report.evidence_quote === "string" ? report.evidence_quote.trim() : "";
  const facts: Array<{ label: string; value: string }> = [];
  if (category) facts.push({ label: "Category", value: phraseLabel(category, HACK_CATEGORY_LABEL) });
  if (decidedBy) facts.push({ label: "Decided by", value: phraseLabel(decidedBy, DECIDED_BY_LABEL) });
  const hasDetails = facts.length > 0 || Boolean(quote);

  return (
    <>
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-3 py-2",
          hasDetails && "border-b border-hairline",
        )}
      >
        <h3 className="text-sm font-medium text-ink">Hack</h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="inline-flex items-center gap-1.5 text-sm font-medium">
            <StatusMark tone={decided.tone} />
            <span className={markTextClass(decided.tone)}>{decided.label}</span>
          </span>
          {count !== null ? (
            <span className="inline-flex items-baseline gap-1.5">
              <span className="text-sm text-mute">Suspects</span>
              <span className="text-sm font-medium tabular-nums text-ink">{count}</span>
            </span>
          ) : null}
        </div>
      </div>
      <FactRows rows={facts} separateLast={Boolean(quote)} />
      {quote ? <EvidenceQuote text={quote} /> : null}
    </>
  );
}

function ReviewBody({ findings }: { findings: unknown[] }) {
  const rows = findings.filter(isRecord);
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-hairline px-3 py-2">
        <h3 className="text-sm font-medium text-ink">Review</h3>
        <span className="inline-flex items-baseline gap-1.5">
          <span className="text-sm text-mute">Findings</span>
          <span className="text-sm font-medium tabular-nums text-ink">{rows.length}</span>
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-2.5 text-sm text-mute">No findings</p>
      ) : (
        <ul>
          {rows.map((finding, index) => (
            <ReviewRow key={`${String(finding.rubric)}-${index}`} finding={finding} />
          ))}
        </ul>
      )}
    </>
  );
}

function ReviewRow({ finding }: { finding: Record<string, unknown> }) {
  const rubric = typeof finding.rubric === "string" ? finding.rubric.trim() : "";
  const judgment = typeof finding.judgment === "string" ? finding.judgment.trim() : "";
  const summary = typeof finding.summary === "string" ? finding.summary.trim() : "";
  const quote = typeof finding.evidence_quote === "string" ? finding.evidence_quote.trim() : "";
  const tone = judgmentTone(judgment);
  return (
    <li className="border-b border-hairline px-3 py-2.5 last:border-b-0">
      <div className="flex items-start gap-3">
        <StatusMark tone={tone} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-sm font-medium text-ink">
              {rubric ? phraseLabel(rubric, RUBRIC_LABEL) : "Finding"}
            </span>
            <span
              className={cn(
                "shrink-0 text-sm font-medium",
                judgment ? markTextClass(tone) : "text-mute",
              )}
            >
              {judgment ? phraseLabel(judgment, JUDGMENT_LABEL) : "-"}
            </span>
          </div>
          {summary ? <p className="mt-1 text-sm text-body">{summary}</p> : null}
          {quote ? (
            <div className="mt-2">
              <div className="mb-1 text-sm text-mute">Quote</div>
              <QuoteText text={quote} />
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function FactRows({
  rows,
  separateLast,
}: {
  rows: Array<{ label: string; value: string }>;
  separateLast: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <dl>
      {rows.map((row, index) => {
        const last = index === rows.length - 1;
        return (
          <div
            key={row.label}
            className={cn(
              "grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3 px-3 py-2.5",
              (!last || separateLast) && "border-b border-hairline",
            )}
          >
            <dt className="text-sm text-mute">{row.label}</dt>
            <dd className="min-w-0 text-sm text-ink">{row.value}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function EvidenceQuote({ text }: { text: string }) {
  return (
    <div className="px-3 py-2.5">
      <div className="mb-1 text-sm text-mute">Quote</div>
      <QuoteText text={text} />
    </div>
  );
}

function QuoteText({ text }: { text: string }) {
  return (
    <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
      {text}
    </pre>
  );
}

function StatusMark({ tone, className }: { tone: MarkTone; className?: string }) {
  const icon = cn("h-4 w-4 shrink-0", className);
  if (tone === "bad") {
    return <CircleX className={cn(icon, "text-error")} aria-hidden />;
  }
  if (tone === "warn") {
    return <CircleAlert className={cn(icon, "text-warning")} aria-hidden />;
  }
  if (tone === "none") {
    return <span className={cn("inline-block h-4 w-4 shrink-0", className)} aria-hidden />;
  }
  return <CircleCheck className={cn(icon, "text-nav-home")} aria-hidden />;
}

function markTextClass(tone: MarkTone): string {
  if (tone === "bad") return "text-error";
  if (tone === "warn") return "text-warning";
  return "text-ink";
}

function hackDecision(report: Record<string, unknown>): { label: string; tone: MarkTone } {
  if (report.is_hack === true) return { label: "Hack found", tone: "bad" };
  if (report.is_hack === false) return { label: "No hack", tone: "ok" };
  return { label: "Not decided", tone: "warn" };
}

function judgmentTone(judgment: string): MarkTone {
  if (judgment === "not_observed" || judgment === "met") return "ok";
  if (judgment === "confirmed" || judgment === "missed") return "bad";
  if (judgment === "suspected" || judgment === "unclear") return "warn";
  return "none";
}

function phraseLabel(value: string, known: Record<string, string>): string {
  const mapped = known[value];
  if (mapped) return mapped;
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
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
