import { Check, Copy } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BuiltinMark } from "@/components/builtin-mark";
import { Button } from "@/components/ui/button";
import { UnderlineTabs } from "@/components/underline-tabs";
import {
  compareValues,
  nextSort,
  SortableHead,
  type SortDir,
} from "@/components/sortable-head";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  encodeDatasetId,
  environmentFromOverlay,
  latestPackageByDataset,
  listPackages,
  overlayAgentProfiles,
  pluginsUsedBySuite,
  uniqueAgentRefs,
  type PackageRelease,
  type SuiteRow,
} from "@/lib/api";
import { getGithubUser, getToken } from "@/lib/auth";
import { ResultOwnerOps } from "@/components/result-owner-ops";
import {
  displayLabelsFromOverlay,
  formatScore,
  reasoningEffortFromOverlay,
} from "@/lib/utils";
import { CodeHighlight } from "@/lib/code-highlight";
import {
  formatPassMetric,
  metricsNAttempts,
  passAtPrimaryK,
  passPowerPrimaryK,
  primaryDisplayK,
} from "@/lib/suite-metrics";
import { BrandMark } from "@/components/brand-mark";
import { HoverTip, TruncateTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import { resolveMechanismMark } from "@/lib/brand-marks";
import { JobOverlayPreview } from "@/components/overlay-file-panel";
import { ScrollTable } from "@/components/scroll-table";

/** Shared column widths — keep Harness/Model tight so columns stay similar. */
const COL_TEXT = "w-[6.5rem] max-w-[6.5rem] overflow-hidden";
const COL_METRIC = "w-[5.5rem] max-w-[5.5rem]";

/** Compact suite id for cells; full id in title. System ids are bare 8-hex. */
function shortSuiteId(id: string): string {
  const raw = id.trim();
  if (/^[0-9a-f]+$/i.test(raw)) {
    return raw.length <= 8 ? raw : raw.slice(0, 8);
  }
  if (raw.length <= 12) return raw;
  return `${raw.slice(0, 10)}…`;
}

/** Render secret-free job_overlay as ageval.profiles/1 YAML for rehydrate display. */
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
    // Locator name only — never a secret value.
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

function CodeBlock({
  path,
  content,
  maxHeightClass = "max-h-56",
}: {
  path: string;
  content: string;
  maxHeightClass?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="relative rounded-[6px] border border-hairline bg-code-bg">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onCopy}
        aria-label="Copy"
        className="absolute right-1.5 top-1.5 z-10 h-7 w-7 shrink-0"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-ink" />
        ) : (
          <Copy className="h-3.5 w-3.5 text-mute" />
        )}
      </Button>
      <pre
        className={`m-0 overflow-auto p-3 pr-10 font-mono text-[12px] leading-5 whitespace-pre ${maxHeightClass}`}
      >
        <code>
          <CodeHighlight path={path} content={content} />
        </code>
      </pre>
    </div>
  );
}

type SortKey =
  | "agent_label"
  | "model_label"
  | "environment"
  | "pass_rate"
  | "mean_score"
  | "n_attempts"
  | "pass_at_k"
  | "pass_power_k"
  | "tasks"
  | "uploaded_by"
  | "suite_run_id";

function suiteSortValue(s: SuiteRow, key: SortKey): unknown {
  const m = s.metrics || {};
  switch (key) {
    case "agent_label":
      return displayLabelsFromOverlay(s.job_overlay).agent || s.agent_label || "";
    case "model_label":
      return s.model_label || "";
    case "environment":
      return environmentFromOverlay(s.job_overlay) || "";
    case "pass_rate":
      return s.pass_rate ?? null;
    case "mean_score":
      return s.mean_score ?? null;
    case "n_attempts":
      return metricsNAttempts(m);
    case "pass_at_k":
      return passAtPrimaryK(m).value;
    case "pass_power_k":
      return passPowerPrimaryK(m).value;
    case "tasks": {
      if (typeof m.n_tasks === "number") return m.n_tasks;
      if (Array.isArray(s.task_refs)) return s.task_refs.length;
      return null;
    }
    case "uploaded_by":
      return s.uploaded_by || "";
    case "suite_run_id":
      return s.suite_run_id || "";
    default:
      return null;
  }
}

function defaultCompare(a: SuiteRow, b: SuiteRow): number {
  const pr = (b.pass_rate ?? -1) - (a.pass_rate ?? -1);
  if (pr !== 0) return pr;
  const ms = (b.mean_score ?? -1) - (a.mean_score ?? -1);
  if (ms !== 0) return ms;
  return (Number(b.created_at) || 0) - (Number(a.created_at) || 0);
}

/**
 * Dataset Leaderboard (#40 + #59 + #60).
 * Rank by observational metrics only — never suite PASS.
 * Job axis = profiles.yaml / job_overlay (not per-task role topology).
 *
 * Default sort: pass_rate desc → mean_score desc → created_at desc.
 * Column headers are clickable (Viewer Jobs pattern). pass@k / pass^k sort by
 * primary display k (max k_values / n_attempts); not job identity.
 */
type ExpandTab = "profiles" | "plugin" | "jobs" | "share";

function SuiteJobsList({
  suite,
  datasetId,
  onOpen,
}: {
  suite: SuiteRow;
  datasetId: string;
  onOpen: (href: string) => void;
}) {
  const rows = suiteJobRows(suite);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-mute">
        No task results on this suite. Upload with{" "}
        <code className="font-mono">ageval results upload-suite</code>.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-mute">
        Each row is this suite&apos;s result for one task. Click a row with
        uploaded Attempt evidence to open the same job detail as Task Jobs.
      </p>
      <ScrollTable
        headers={["Task", "Status", "Score", "Attempt"]}
        rows={rows.map((j) => {
          const href =
            j.hasAttempt && j.runId
              ? `/datasets/${encodeDatasetId(datasetId)}/tasks/${encodeURIComponent(j.taskId)}/attempts/${encodeURIComponent(j.runId)}`
              : null;
          return {
            key: j.key,
            onClick: href ? () => onOpen(href) : undefined,
            muted: !href,
            cells: [
              <span key="t" className="font-mono text-xs">
                {j.taskId}
              </span>,
              j.status || "—",
              formatScore(j.score),
              j.runId ? (
                <span key="r" className="font-mono text-xs">
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
            ],
          };
        })}
      />
    </div>
  );
}

function suiteJobRows(suite: SuiteRow): Array<{
  key: string;
  taskId: string;
  runId: string | null;
  status: string | null;
  score: number | null;
  hasAttempt: boolean;
}> {
  const rows: Array<{
    key: string;
    taskId: string;
    runId: string | null;
    status: string | null;
    score: number | null;
    hasAttempt: boolean;
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
      });
    }
  }
  return rows;
}

export function LeaderboardTable({
  suites,
  datasetId,
  orgId,
  emptyTitle,
  emptyBody,
  openSuiteId,
  packageDigest,
  versions,
  onSuiteUpdated,
  onSuiteDeleted,
}: {
  suites: SuiteRow[];
  datasetId: string;
  /** Dataset owning org — used to pick `my-lab/nooa` over another org's copy. */
  orgId?: string | null;
  emptyTitle?: string;
  emptyBody?: string;
  /** Open this public-board row on load; ignored when the suite is absent. */
  openSuiteId?: string | null;
  /** Currently viewed Dataset release digest (fallback for overlay preview). */
  packageDigest?: string;
  versions?: PackageRelease[];
  onSuiteUpdated?: (suiteRunId: string, patch: Partial<SuiteRow>) => void;
  onSuiteDeleted?: (suiteRunId: string) => void;
}) {
  const navigate = useNavigate();
  const selfLogin = (getGithubUser() || "").toLowerCase();
  const [openId, setOpenId] = useState<string | null>(null);
  const [expandTab, setExpandTab] = useState<ExpandTab>("profiles");
  const [sortKey, setSortKey] = useState<string | null>("pass_rate");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [pluginCatalog, setPluginCatalog] = useState<PackageRelease[]>([]);

  useEffect(() => {
    if (!openSuiteId) return;
    if (suites.some((s) => s.suite_run_id === openSuiteId)) {
      setOpenId(openSuiteId);
    }
  }, [openSuiteId, suites]);

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    listPackages(token, { packageKind: "plugin" })
      .then((items) => {
        if (!cancelled) setPluginCatalog(latestPackageByDataset(items));
      })
      .catch(() => {
        if (!cancelled) setPluginCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleRow(id: string) {
    setOpenId((cur) => {
      const next = cur === id ? null : id;
      if (next !== cur) setExpandTab("profiles");
      return next;
    });
  }

  const showKColumns = suites.some(
    (s) => primaryDisplayK(s.metrics || {}) != null,
  );
  const colCount = showKColumns ? 11 : 8;

  const rows = useMemo(() => {
    const list = [...suites];
    if (sortKey && sortDir) {
      const key = sortKey as SortKey;
      list.sort((a, b) => {
        const cmp = compareValues(
          suiteSortValue(a, key),
          suiteSortValue(b, key),
          sortDir,
        );
        if (cmp !== 0) return cmp;
        return defaultCompare(a, b);
      });
    } else {
      list.sort(defaultCompare);
    }
    return list;
  }, [suites, sortKey, sortDir]);

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
  }

  function head(key: string, label: string, alignRight?: boolean) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
        className={alignRight ? "ml-auto" : undefined}
      />
    );
  }

  if (suites.length === 0) {
    return (
      <div className="rounded-[8px] border border-hairline bg-canvas-soft p-6 space-y-3">
        <p className="text-sm font-medium text-ink">
          {emptyTitle || "No Leaderboard rows yet"}
        </p>
        <p className="text-sm text-mute">
          {emptyBody ||
            "Public board lists complete, release-bound suite uploads only. Incomplete or draft-bound runs stay on Internal and the task Jobs list. Upload with ageval results upload-suite. Metrics are observational, not a suite-level PASS."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-mute">
        <span className="font-mono">{datasetId}</span>
        {" · "}metrics only (not suite PASS)
        {" · "}click headers to sort
        {showKColumns ? " · pass@k uses job max k" : null}
      </p>
      <div className="rounded-[8px] border border-hairline overflow-x-auto">
        <Table className="table-fixed w-full">
          <TableHeader>
            <TableRow>
              <TableHead className={COL_TEXT}>
                {head("agent_label", "Harness")}
              </TableHead>
              <TableHead className={COL_TEXT}>
                {head("model_label", "Model")}
              </TableHead>
              <TableHead className={COL_METRIC}>
                {head("environment", "Environment")}
              </TableHead>
              <TableHead className={`text-right ${COL_METRIC}`}>
                {head("pass_rate", "Pass rate", true)}
              </TableHead>
              <TableHead className={`text-right ${COL_METRIC}`}>
                {head("mean_score", "Mean score", true)}
              </TableHead>
              {showKColumns ? (
                <>
                  <TableHead className={`text-right ${COL_METRIC}`}>
                    {head("n_attempts", "n_attempts", true)}
                  </TableHead>
                  <TableHead className={`text-right ${COL_METRIC}`}>
                    <HoverTip content="Largest k from metrics.k_values / n_attempts; cell labels @k">
                      <span className="inline-flex">{head("pass_at_k", "pass@k", true)}</span>
                    </HoverTip>
                  </TableHead>
                  <TableHead className={`text-right ${COL_METRIC}`}>
                    <HoverTip content="Same display k as pass@k; cell labels ^k">
                      <span className="inline-flex">{head("pass_power_k", "pass^k", true)}</span>
                    </HoverTip>
                  </TableHead>
                </>
              ) : null}
              <TableHead className={`text-right ${COL_METRIC}`}>
                {head("tasks", "Tasks", true)}
              </TableHead>
              <TableHead className={COL_TEXT}>
                {head("uploaded_by", "Uploader")}
              </TableHead>
              <TableHead className={COL_METRIC}>
                {head("suite_run_id", "Suite run")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) => {
              const m = s.metrics || {};
              const nTasks =
                typeof m.n_tasks === "number"
                  ? m.n_tasks
                  : Array.isArray(s.task_refs)
                    ? s.task_refs.length
                    : null;
              const nPass = typeof m.n_pass === "number" ? m.n_pass : null;
              const open = openId === s.suite_run_id;
              const yamlText = jobOverlayToProfilesYaml(s.job_overlay);
              const overlayDigest =
                versions?.find((row) => row.version === s.dataset_version)
                  ?.package_digest || packageDigest;
              const plugins = pluginsUsedBySuite(s, pluginCatalog, orgId);
              const rehydrateScript = [
                "# Export this suite's job binding as profiles.yaml (locators only; no secrets)",
                `ageval results export-profiles ${s.suite_run_id} --out profiles.from-suite.yaml`,
                "",
                "# Re-run with that binding (fill Dataset .env locally for credentials)",
                "ageval run <dataset-root> --profiles profiles.from-suite.yaml",
                "",
              ].join("\n");
              const nAtt = metricsNAttempts(m);
              const atK = passAtPrimaryK(m);
              const powK = passPowerPrimaryK(m);
              const derived = displayLabelsFromOverlay(s.job_overlay);
              const agentText = derived.agent || s.agent_label || "";
              const modelText = derived.model || s.model_label || "";
              const runtimeLinks = uniqueAgentRefs(s.agent_refs);
              const environment = environmentFromOverlay(s.job_overlay) || "";
              const environmentKey = resolveMechanismMark(environment);

              return (
                <Fragment key={s.suite_run_id}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => toggleRow(s.suite_run_id)}
                    data-state={open ? "open" : undefined}
                  >
                    {runtimeLinks.length ? (
                      <TableCell className={COL_TEXT}>
                        <span className="flex flex-col gap-0.5 min-w-0">
                          {runtimeLinks.map((ref) => (
                            <Link
                              key={ref.package_id}
                              to={`/agents/${encodeDatasetId(ref.package_id)}`}
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex max-w-full text-sm hover:text-ink hover:underline underline-offset-2"
                            >
                              <TruncateTip
                                text={ref.package_id}
                                className="text-sm"
                              />
                            </Link>
                          ))}
                        </span>
                      </TableCell>
                    ) : (
                      <TableCell className={COL_TEXT}>
                        <TruncateTip
                          text={agentText || "—"}
                          className="text-sm"
                        />
                      </TableCell>
                    )}
                    <TableCell className={COL_TEXT}>
                      <ModelLabel
                        value={modelText}
                        effort={reasoningEffortFromOverlay(s.job_overlay)}
                        className="font-mono text-xs"
                      />
                    </TableCell>
                    <TableCell
                      className={`font-mono text-xs ${COL_METRIC}`}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {environmentKey ? (
                          <BrandMark
                            mark={{ kind: "catalog", id: environmentKey }}
                            size={16}
                          />
                        ) : null}
                        {environment || "—"}
                      </span>
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                    >
                      {s.pass_rate == null
                        ? "—"
                        : `${(Number(s.pass_rate) * 100).toFixed(1)}%`}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                    >
                      {formatScore(s.mean_score)}
                    </TableCell>
                    {showKColumns ? (
                      <>
                        <TableCell
                          className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                        >
                          {nAtt == null ? "—" : String(nAtt)}
                        </TableCell>
                        <TableCell
                          className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                        >
                          {atK.value == null ? (
                            "—"
                          ) : (
                            <HoverTip content={`pass@${atK.k}`}>
                              <span>
                              {formatPassMetric(atK.value)}
                              <span className="ml-1 text-mute">@{atK.k}</span>
                              </span>
                            </HoverTip>
                          )}
                        </TableCell>
                        <TableCell
                          className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                        >
                          {powK.value == null ? (
                            "—"
                          ) : (
                            <HoverTip content={`pass^${powK.k}`}>
                              <span>
                              {formatPassMetric(powK.value)}
                              <span className="ml-1 text-mute">^{powK.k}</span>
                              </span>
                            </HoverTip>
                          )}
                        </TableCell>
                      </>
                    ) : null}
                    <TableCell
                      className={`text-right tabular-nums text-xs ${COL_METRIC}`}
                    >
                      {nPass != null && nTasks != null
                        ? `${nPass}/${nTasks}`
                        : nTasks != null
                          ? String(nTasks)
                          : "—"}
                    </TableCell>
                    <TableCell className={`font-mono text-xs ${COL_TEXT}`}>
                      <HoverTip content={s.uploaded_by || undefined}>
                        <span className="block truncate">
                          {s.uploaded_by || "—"}
                        </span>
                      </HoverTip>
                    </TableCell>
                    <TableCell
                      className={`font-mono text-[11px] ${COL_METRIC}`}
                    >
                      <HoverTip content={s.suite_run_id}>
                        <span className="block truncate">
                          {shortSuiteId(s.suite_run_id)}
                        </span>
                      </HoverTip>
                    </TableCell>
                  </TableRow>
                  {open ? (
                    <TableRow>
                      <TableCell colSpan={colCount} className="bg-canvas-soft">
                        <div
                          className="space-y-3 py-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {showKColumns && atK.k != null ? (
                            <p className="text-xs text-mute">
                              Observational k metrics for this job (not PASS
                              authority; not identity). Display k=
                              <span className="font-mono">{atK.k}</span>
                              {nAtt != null ? (
                                <>
                                  {" "}
                                  · n_attempts=
                                  <span className="font-mono">{nAtt}</span>
                                </>
                              ) : null}
                              .
                            </p>
                          ) : null}
                          <UnderlineTabs
                            size="sm"
                            ariaLabel="Suite details"
                            value={expandTab}
                            onChange={setExpandTab}
                            items={[
                              { id: "profiles" as const, label: "profiles" },
                              { id: "plugin" as const, label: "plugin" },
                              { id: "jobs" as const, label: "jobs" },
                              ...(((s.uploaded_by || "").toLowerCase() ===
                              selfLogin
                                ? ([{ id: "share" as const, label: "share" }] as const)
                                : []) as ReadonlyArray<{
                                id: ExpandTab;
                                label: string;
                              }>),
                            ]}
                          />
                          {expandTab === "profiles" ? (
                            <>
                              <CodeBlock
                                path="profiles.yaml"
                                content={yamlText}
                                maxHeightClass="max-h-56"
                              />
                              <CodeBlock
                                path="rehydrate.sh"
                                content={rehydrateScript}
                                maxHeightClass="max-h-40"
                              />
                              <JobOverlayPreview
                                overlay={s.job_overlay}
                                datasetId={datasetId}
                                datasetDigest={overlayDigest || ""}
                              />
                            </>
                          ) : expandTab === "plugin" ? (
                            <div className="space-y-2">
                              {plugins.length === 0 ? (
                                <p className="text-sm text-mute">
                                  No plugins recorded for this job.
                                </p>
                              ) : (
                                <ul className="divide-y divide-hairline rounded-[6px] border border-hairline bg-canvas">
                                  {plugins.map((p) => {
                                    const bundled = pluginCatalog.some(
                                      (row) =>
                                        row.dataset_id === p.plugin_id &&
                                        row.builtin,
                                    );
                                    return (
                                    <li key={p.plugin_id}>
                                      <Link
                                        to={`/plugins/${encodeDatasetId(p.plugin_id)}`}
                                        className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-row-hover"
                                      >
                                        <span className="inline-flex min-w-0 items-center gap-1.5 font-mono text-xs text-ink">
                                          {p.plugin_id}
                                          {bundled ? <BuiltinMark /> : null}
                                        </span>
                                        <span className="font-mono text-[11px] text-mute">
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
                          ) : expandTab === "share" ? (
                            <ResultOwnerOps
                              kind="suite"
                              resultId={s.suite_run_id}
                              visibility={s.visibility}
                              canManage
                              token={getToken()}
                              onVisibility={(next) =>
                                onSuiteUpdated?.(s.suite_run_id, {
                                  visibility: next,
                                })
                              }
                              onDeleted={() => {
                                setOpenId(null);
                                onSuiteDeleted?.(s.suite_run_id);
                              }}
                            />
                          ) : (
                            <SuiteJobsList
                              suite={s}
                              datasetId={datasetId}
                              onOpen={(href) => navigate(href)}
                            />
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
