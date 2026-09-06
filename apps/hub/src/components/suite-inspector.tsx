import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BrandMark } from "@/components/brand-mark";
import { BuiltinMark } from "@/components/builtin-mark";
import { CodeFence } from "@/components/code-fence";
import { TruncateTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import { JobOverlayPreview } from "@/components/overlay-file-panel";
import { ResultOwnerOps } from "@/components/result-owner-ops";
import { ScoreRing } from "@/components/score-ring";
import { ScrollTable } from "@/components/scroll-table";
import { Input } from "@/components/ui/input";
import { TableColumnPicker } from "@/components/ui/table-column-picker";
import { UnderlineTabs } from "@/components/underline-tabs";
import { useTableColumns } from "@/hooks/use-table-columns";
import {
  decodeFileContent,
  encodeDatasetId,
  environmentFromOverlay,
  getAttemptFile,
  overlayAgentProfiles,
  pluginsUsedBySuite,
  type PackageRelease,
  type SuiteRow,
} from "@/lib/api";
import {
  clockFromSummaryJson,
  toArchivePath,
} from "@/lib/attempt-evidence";
import { getToken } from "@/lib/auth";
import { resolveMechanismMark } from "@/lib/brand-marks";
import {
  displayLabelsFromOverlay,
  formatDay,
  formatScore,
  reasoningEffortFromOverlay,
} from "@/lib/utils";

export type SuiteInspectorTab = "profiles" | "plugin" | "jobs" | "share";

/** Compact suite id for cells; full id in title. System ids are bare 8-hex. */
export function shortSuiteId(id: string): string {
  const raw = id.trim();
  if (/^[0-9a-f]+$/i.test(raw)) {
    return raw.length <= 8 ? raw : raw.slice(0, 8);
  }
  if (raw.length <= 12) return raw;
  return `${raw.slice(0, 10)}…`;
}

export function suiteDetailPath(
  datasetId: string,
  suiteRunId: string,
  query?: Record<string, string | null | undefined>,
): string {
  const path = `/datasets/${encodeDatasetId(datasetId)}/suites/${encodeURIComponent(suiteRunId)}`;
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    const trimmed = (value || "").trim();
    if (trimmed) params.set(key, trimmed);
  }
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function jobOverlayToProfilesYaml(overlay: SuiteRow["job_overlay"]): string {
  const profiles = overlayAgentProfiles(overlay);
  const environment = environmentFromOverlay(overlay);
  if (!environment && !Object.keys(profiles).length) {
    return "# no job_overlay on this suite\n";
  }
  const lines: string[] = ["format: ageval.profiles/1"];
  if (environment) lines.push(`environment: ${environment}`);
  lines.push("agent_profiles:");
  const roles = Object.keys(profiles).sort();
  if (roles.length === 0) {
    lines.push("  {}");
    return lines.join("\n") + "\n";
  }
  for (const role of roles) {
    const b = profiles[role];
    if (!b || typeof b !== "object") continue;
    lines.push(`  ${role}:`);
    if (b.executor != null) lines.push(`    executor: ${String(b.executor)}`);
    if (b.options && typeof b.options === "object" && b.options.entry != null) {
      lines.push("    options:");
      lines.push(`      entry: ${String(b.options.entry)}`);
    }
    if (b.model != null) lines.push(`    model: ${String(b.model)}`);
    if (b.base_url != null) lines.push(`    base_url: ${String(b.base_url)}`);
    if (b.api_key != null) lines.push(`    api_key: ${String(b.api_key)}`);
    const overlays = Array.isArray(b.overlays) ? b.overlays.filter(Boolean) : [];
    if (overlays.length) {
      lines.push("    overlays:");
      for (const path of overlays) {
        lines.push(`      - ${String(path)}`);
      }
    }
  }
  return lines.join("\n") + "\n";
}

const JOB_OPTIONAL_COLUMNS = [
  { id: "attempt", label: "Attempt" },
  { id: "started", label: "Started" },
  { id: "duration", label: "Duration" },
] as const;
const JOB_OPTIONAL_IDS = JOB_OPTIONAL_COLUMNS.map((col) => col.id);
const JOB_OPTIONAL_DEFAULT: typeof JOB_OPTIONAL_IDS = ["started", "duration"];

type AttemptClock = { started: string | null; duration: string | null };

async function readAttemptClock(
  runId: string,
  token: string | null,
): Promise<AttemptClock> {
  const file = await getAttemptFile(
    runId,
    toArchivePath("summary.json", runId),
    token,
  );
  return clockFromSummaryJson(decodeFileContent(file));
}

function jobStartedAt(
  ref: NonNullable<SuiteRow["task_refs"]>[number],
  runId: string | null,
): string | null {
  const own = typeof ref.started_at === "string" ? ref.started_at.trim() : "";
  if (runId && runId === (ref.run_id || "").trim() && own) return own;
  if (runId) {
    for (const prev of ref.previous || []) {
      if (prev.run_id !== runId) continue;
      const started =
        typeof prev.started_at === "string" ? prev.started_at.trim() : "";
      if (started) return started;
    }
  }
  return own || null;
}

function suiteJobRows(suite: SuiteRow): Array<{
  key: string;
  taskId: string;
  runId: string | null;
  status: string | null;
  score: number | null;
  hasAttempt: boolean;
  startedAt: string | null;
}> {
  const rows: Array<{
    key: string;
    taskId: string;
    runId: string | null;
    status: string | null;
    score: number | null;
    hasAttempt: boolean;
    startedAt: string | null;
  }> = [];
  for (const ref of suite.task_refs || []) {
    const taskId = (ref.task_id || "").trim();
    if (!taskId) continue;
    const ids =
      Array.isArray(ref.attempt_run_ids) && ref.attempt_run_ids.length
        ? ref.attempt_run_ids.filter((id): id is string => Boolean(id))
        : ref.run_id
          ? [ref.run_id]
          : [];
    if (ids.length === 0) {
      rows.push({
        key: `${suite.suite_run_id}:${taskId}:none`,
        taskId,
        runId: null,
        status: ref.status ?? null,
        score: ref.score ?? null,
        hasAttempt: false,
        startedAt: jobStartedAt(ref, null),
      });
      continue;
    }
    for (const runId of ids) {
      rows.push({
        key: `${suite.suite_run_id}:${taskId}:${runId}`,
        taskId,
        runId,
        status: ref.status ?? null,
        score: ref.score ?? null,
        hasAttempt: Boolean(ref.has_attempt_content) && Boolean(runId),
        startedAt: jobStartedAt(ref, runId),
      });
    }
  }
  return rows;
}

function SuiteJobsList({
  suite,
  datasetId,
}: {
  suite: SuiteRow;
  datasetId: string;
}) {
  const navigate = useNavigate();
  const rows = useMemo(() => suiteJobRows(suite), [suite]);
  const [query, setQuery] = useState("");
  const [clocks, setClocks] = useState<Record<string, AttemptClock>>({});
  const [jobColumns, setJobColumns] = useTableColumns(
    "ageval.hub.columns.suite-jobs.v3",
    JOB_OPTIONAL_IDS,
    JOB_OPTIONAL_DEFAULT,
  );
  const showAttempt = jobColumns.includes("attempt");
  const showStarted = jobColumns.includes("started");
  const showDuration = jobColumns.includes("duration");

  useEffect(() => {
    const ids = [
      ...new Set(
        rows
          .map((row) => row.runId)
          .filter((id): id is string => Boolean(id)),
      ),
    ];
    if (!ids.length) {
      setClocks({});
      return;
    }
    let cancelled = false;
    const token = getToken();
    const next: Record<string, AttemptClock> = {};
    async function run() {
      let cursor = 0;
      async function worker() {
        while (cursor < ids.length) {
          const id = ids[cursor];
          cursor += 1;
          if (!id) continue;
          try {
            next[id] = await readAttemptClock(id, token);
          } catch {
            next[id] = { started: null, duration: null };
          }
        }
      }
      await Promise.all(
        Array.from({ length: Math.min(8, ids.length) }, () => worker()),
      );
      if (!cancelled) setClocks(next);
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => {
      const clock = row.runId ? clocks[row.runId] : undefined;
      const started = clock?.started || row.startedAt;
      const hay = [
        row.taskId,
        row.status || "",
        row.runId || "",
        row.score == null ? "" : formatScore(row.score),
        started ? formatDay(started) : "",
        clock?.duration || "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [query, rows, clocks]);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-mute">
        No task results on this suite. Upload with{" "}
        <code className="font-mono">ageval results upload-suite</code>.
      </p>
    );
  }

  const headers = [
    "Task",
    "Status",
    "Score",
    ...(showAttempt ? ["Attempt"] : []),
    ...(showStarted ? ["Started"] : []),
    ...(showDuration ? ["Duration"] : []),
  ];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search jobs…"
          aria-label="Search jobs"
          className="min-w-0 w-full max-w-sm focus-visible:border-hairline"
        />
        <TableColumnPicker
          className="ml-auto"
          options={JOB_OPTIONAL_COLUMNS}
          value={jobColumns}
          onChange={setJobColumns}
          ariaLabel="Optional job columns"
        />
      </div>
      {filtered.length === 0 ? (
        <p className="text-sm text-mute">No matching jobs</p>
      ) : (
        <ScrollTable
          className="max-h-[min(70vh,40rem)]"
          headers={headers}
          rows={filtered.map((j) => {
            const href =
              j.hasAttempt && j.runId
                ? `/datasets/${encodeDatasetId(datasetId)}/tasks/${encodeURIComponent(j.taskId)}/attempts/${encodeURIComponent(j.runId)}`
                : null;
            const cells = [
              <span key="t">{j.taskId}</span>,
              j.status || "—",
              <ScoreRing key="score" value={j.score}>
                {formatScore(j.score)}
              </ScoreRing>,
            ];
            if (showAttempt) {
              cells.push(
                j.runId ? (
                  <span key="r">
                    {shortSuiteId(j.runId)}
                    {!href ? (
                      <span className="ml-2 font-sans text-[11px] text-mute">
                        summary only
                      </span>
                    ) : null}
                  </span>
                ) : (
                  "—"
                ),
              );
            }
            const clock = j.runId ? clocks[j.runId] : undefined;
            const started = clock?.started || j.startedAt;
            if (showStarted) {
              cells.push(
                <span key="started" className="tabular-nums">
                  {started ? formatDay(started) : "—"}
                </span>,
              );
            }
            if (showDuration) {
              cells.push(
                <span key="duration" className="tabular-nums">
                  {clock?.duration || "—"}
                </span>,
              );
            }
            return {
              key: j.key,
              onClick: href ? () => navigate(href) : undefined,
              muted: !href,
              cells,
            };
          })}
        />
      )}
    </div>
  );
}

export function SuiteInspector({
  suite,
  datasetId,
  overlayDigest,
  pluginCatalog,
  orgId,
  canManage,
  tab,
  onTabChange,
  onSuiteUpdated,
  onSuiteDeleted,
  canDetachPerformance = false,
  onRemovePerformance,
}: {
  suite: SuiteRow;
  datasetId: string;
  overlayDigest?: string;
  pluginCatalog: PackageRelease[];
  orgId?: string | null;
  canManage: boolean;
  tab: SuiteInspectorTab;
  onTabChange: (tab: SuiteInspectorTab) => void;
  onSuiteUpdated?: (suiteRunId: string, patch: Partial<SuiteRow>) => void;
  onSuiteDeleted?: (suiteRunId: string) => void;
  canDetachPerformance?: boolean;
  onRemovePerformance?: () => void;
}) {
  const m = suite.metrics || {};
  const nTasks =
    typeof m.n_tasks === "number"
      ? m.n_tasks
      : Array.isArray(suite.task_refs)
        ? suite.task_refs.length
        : null;
  const nPass = typeof m.n_pass === "number" ? m.n_pass : null;
  const derived = displayLabelsFromOverlay(suite.job_overlay);
  const agentText = derived.agent || suite.agent_label || "";
  const modelText = derived.model || suite.model_label || "";
  const environment = environmentFromOverlay(suite.job_overlay) || "";
  const environmentKey = resolveMechanismMark(environment);
  const yamlText = jobOverlayToProfilesYaml(suite.job_overlay);
  const plugins = pluginsUsedBySuite(suite, pluginCatalog, orgId);
  const rehydrateScript = [
    "# Export this suite's job binding as profiles.yaml (locators only; no secrets)",
    `ageval results export-profiles ${suite.suite_run_id} --out profiles.from-suite.yaml`,
    "",
    "# Re-run with that binding (fill Dataset .env locally for credentials)",
    "ageval run <dataset-root> --profiles profiles.from-suite.yaml",
    "",
  ].join("\n");
  const tabItems: { id: SuiteInspectorTab; label: string }[] = [
    { id: "profiles", label: "Profiles" },
    { id: "plugin", label: "Plugin" },
    { id: "jobs", label: "Jobs" },
  ];
  if (canManage) tabItems.push({ id: "share", label: "Share" });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="truncate font-mono text-2xl font-semibold tracking-tight text-ink">
            {suite.suite_run_id}
          </h1>
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink">
            {environmentKey ? (
              <BrandMark
                mark={{ kind: "catalog", id: environmentKey }}
                size={16}
              />
            ) : null}
            {agentText ? (
              <TruncateTip text={agentText} />
            ) : (
              <span className="text-mute">—</span>
            )}
            <span className="text-mute" aria-hidden>
              ·
            </span>
            <ModelLabel
              value={modelText}
              effort={reasoningEffortFromOverlay(suite.job_overlay)}
            />
            {environment ? (
              <>
                <span className="text-mute" aria-hidden>
                  ·
                </span>
                <span className="text-body">{environment}</span>
              </>
            ) : null}
          </div>
          <div className="text-xs text-mute">
            <span className="tabular-nums text-ink">
              {suite.pass_rate == null
                ? "—"
                : `${(Number(suite.pass_rate) * 100).toFixed(1)}%`}
            </span>
            {" · mean "}
            <span className="tabular-nums text-ink">
              {formatScore(suite.mean_score)}
            </span>
            {nPass != null && nTasks != null ? (
              <>
                {" · "}
                <span className="tabular-nums text-ink">
                  {nPass}/{nTasks}
                </span>
              </>
            ) : nTasks != null ? (
              <>
                {" · "}
                <span className="tabular-nums text-ink">{nTasks}</span>
                {" tasks"}
              </>
            ) : null}
            {" · "}
            <TruncateTip
              text={shortSuiteId(suite.suite_run_id)}
              copyValue={suite.suite_run_id}
              copyable
            />
          </div>
        </div>
        {canManage || canDetachPerformance ? (
          <div className="flex shrink-0 items-center gap-0.5">
            <ResultOwnerOps
              kind="suite"
              resultId={suite.suite_run_id}
              visibility={suite.visibility}
              complete={suite.complete}
              boundKind={suite.bound_kind}
              boardListed={suite.board_listed}
              jobOverlay={suite.job_overlay}
              canManage={canManage}
              canDetachPerformance={canDetachPerformance}
              onRemovePerformance={onRemovePerformance}
              variant="delete"
              token={getToken()}
              onDeleted={() => onSuiteDeleted?.(suite.suite_run_id)}
            />
          </div>
        ) : null}
      </div>
      <UnderlineTabs
        ariaLabel="Suite details"
        value={tab}
        onChange={onTabChange}
        items={tabItems}
      />
      {tab === "profiles" ? (
        <div className="space-y-3">
          <CodeFence
            path="profiles.yaml"
            content={yamlText}
            maxHeightClass="max-h-[min(50vh,28rem)]"
          />
          <CodeFence
            path="rehydrate.sh"
            content={rehydrateScript}
            maxHeightClass="max-h-56"
          />
          <JobOverlayPreview
            overlay={suite.job_overlay}
            datasetId={datasetId}
            datasetDigest={overlayDigest || ""}
          />
        </div>
      ) : tab === "plugin" ? (
        <div className="space-y-2">
          {plugins.length === 0 ? (
            <p className="text-sm text-mute">
              No plugins recorded for this job.
            </p>
          ) : (
            <ul className="divide-y divide-hairline rounded-[14px] border border-hairline bg-canvas">
              {plugins.map((p) => {
                const bundled = pluginCatalog.some(
                  (row) =>
                    row.dataset_id === p.plugin_id && row.builtin,
                );
                return (
                  <li key={p.plugin_id}>
                    <Link
                      to={`/plugins/${encodeDatasetId(p.plugin_id)}`}
                      className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-row-hover"
                    >
                      <span className="inline-flex min-w-0 items-center gap-1.5 text-link hover:text-link-deep">
                        {p.plugin_id}
                        {bundled ? <BuiltinMark /> : null}
                      </span>
                      <span className="text-xs text-mute">
                        {bundled
                          ? "bundled"
                          : p.version
                            ? `v${p.version}`
                            : "marketplace"}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : tab === "share" ? (
        <div className="space-y-4">
          <ResultOwnerOps
            kind="suite"
            resultId={suite.suite_run_id}
            visibility={suite.visibility}
            complete={suite.complete}
            boundKind={suite.bound_kind}
            boardListed={suite.board_listed}
            jobOverlay={suite.job_overlay}
            canManage
            variant="panel"
            token={getToken()}
            onVisibility={(next) =>
              onSuiteUpdated?.(suite.suite_run_id, {
                visibility: next,
              })
            }
            onAttached={(row) =>
              onSuiteUpdated?.(suite.suite_run_id, row)
            }
          />
        </div>
      ) : (
        <SuiteJobsList suite={suite} datasetId={datasetId} />
      )}
    </div>
  );
}
