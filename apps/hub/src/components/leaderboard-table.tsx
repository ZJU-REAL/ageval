import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

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
  environmentFromOverlay,
  uniqueAgentRefs,
  type SuiteRow,
} from "@/lib/api";
import { agentPackageHref } from "@/lib/agent-models";
import {
  displayLabelsFromOverlay,
  formatScore,
  reasoningEffortFromOverlay,
} from "@/lib/utils";
import {
  formatPassMetric,
  passAtPrimaryK,
  passPowerPrimaryK,
} from "@/lib/suite-metrics";
import { BrandMark } from "@/components/brand-mark";
import { HoverTip, TruncateTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import { ScoreRing } from "@/components/score-ring";
import { resolveMechanismMark } from "@/lib/brand-marks";
import { shortSuiteId } from "@/components/suite-inspector";

const COL_TEXT = "max-w-[12rem] overflow-hidden";
const COL_METRIC = "w-[6.5rem]";
const COL_SCORE = "w-[8.5rem]";

export const LEADERBOARD_OPTIONAL_COLUMNS = [
  { id: "pass_at_k", label: "pass@k" },
  { id: "pass_power_k", label: "pass^k" },
  { id: "suite_run_id", label: "Suite run" },
] as const;

export type LeaderboardOptionalColumn =
  (typeof LEADERBOARD_OPTIONAL_COLUMNS)[number]["id"];

export const LEADERBOARD_OPTIONAL_IDS = LEADERBOARD_OPTIONAL_COLUMNS.map(
  (col) => col.id,
);
export const LEADERBOARD_OPTIONAL_DEFAULT: readonly LeaderboardOptionalColumn[] =
  [];

type SortKey =
  | "agent_label"
  | "model_label"
  | "environment"
  | "pass_rate"
  | "mean_score"
  | "pass_at_k"
  | "pass_power_k"
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
    case "pass_at_k":
      return passAtPrimaryK(m).value;
    case "pass_power_k":
      return passPowerPrimaryK(m).value;
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
 * Row click opens the suite run detail page (not an in-table expand).
 */
export function LeaderboardTable({
  suites,
  datasetId,
  emptyTitle,
  emptyBody,
  onOpenSuite,
  optionalColumns = [],
}: {
  suites: SuiteRow[];
  datasetId: string;
  emptyTitle?: string;
  emptyBody?: string;
  onOpenSuite?: (suiteRunId: string | null) => void;
  optionalColumns?: readonly LeaderboardOptionalColumn[];
}) {
  const [sortKey, setSortKey] = useState<string | null>("pass_rate");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const show = new Set(optionalColumns);

  useEffect(() => {
    if (
      sortKey === "pass_at_k" ||
      sortKey === "pass_power_k" ||
      sortKey === "suite_run_id"
    ) {
      if (!optionalColumns.includes(sortKey)) {
        setSortKey("pass_rate");
        setSortDir("desc");
      }
    }
  }, [optionalColumns, sortKey]);

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

  function head(key: string, label: string) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
      />
    );
  }

  if (suites.length === 0) {
    return (
      <div className="blob-panel p-6 space-y-3">
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

  return (
    <div className="space-y-3">
      <p className="text-xs text-mute">
        <span>{datasetId}</span>
        {" · "}metrics only (not suite PASS)
        {" · "}click headers to sort
        {show.has("pass_at_k") || show.has("pass_power_k")
          ? " · pass@k uses job max k"
          : null}
      </p>
      <div className="blob-panel overflow-x-auto">
        <Table className="w-full">
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
              <TableHead className={COL_SCORE}>
                {head("pass_rate", "Pass rate")}
              </TableHead>
              <TableHead className={COL_SCORE}>
                {head("mean_score", "Mean score")}
              </TableHead>
              {show.has("pass_at_k") ? (
                <TableHead className={COL_SCORE}>
                  <HoverTip content="Largest k from metrics.k_values / n_attempts; cell labels @k">
                    <span className="inline-flex">{head("pass_at_k", "pass@k")}</span>
                  </HoverTip>
                </TableHead>
              ) : null}
              {show.has("pass_power_k") ? (
                <TableHead className={COL_SCORE}>
                  <HoverTip content="Same display k as pass@k; cell labels ^k">
                    <span className="inline-flex">{head("pass_power_k", "pass^k")}</span>
                  </HoverTip>
                </TableHead>
              ) : null}
              <TableHead className={COL_TEXT}>
                {head("uploaded_by", "Uploader")}
              </TableHead>
              {show.has("suite_run_id") ? (
                <TableHead className={COL_METRIC}>
                  {head("suite_run_id", "Suite run")}
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) => {
              const m = s.metrics || {};
              const atK = passAtPrimaryK(m);
              const powK = passPowerPrimaryK(m);
              const derived = displayLabelsFromOverlay(s.job_overlay);
              const agentText = derived.agent || s.agent_label || "";
              const modelText = derived.model || s.model_label || "";
              const runtimeLinks = uniqueAgentRefs(s.agent_refs);
              const environment = environmentFromOverlay(s.job_overlay) || "";
              const environmentKey = resolveMechanismMark(environment);

              return (
                  <TableRow
                    key={s.suite_run_id}
                    className="cursor-pointer"
                    onClick={() => onOpenSuite?.(s.suite_run_id)}
                    role={onOpenSuite ? "link" : undefined}
                    aria-label="Click to open suite run"
                  >
                    {runtimeLinks.length ? (
                      <TableCell className={COL_TEXT}>
                        <span className="flex flex-col gap-0.5 min-w-0">
                          {runtimeLinks.map((ref) => (
                            <Link
                              key={ref.package_id}
                              to={agentPackageHref(ref.package_id)}
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex max-w-full text-link hover:text-link-deep hover:underline underline-offset-2"
                            >
                              <TruncateTip text={ref.package_id} />
                            </Link>
                          ))}
                        </span>
                      </TableCell>
                    ) : (
                      <TableCell className={COL_TEXT}>
                        <TruncateTip text={agentText || "—"} />
                      </TableCell>
                    )}
                    <TableCell className={COL_TEXT}>
                      <ModelLabel
                        value={modelText}
                        effort={reasoningEffortFromOverlay(s.job_overlay)}
                        to={
                          runtimeLinks.length && modelText
                            ? agentPackageHref(
                                runtimeLinks[0].package_id,
                                modelText,
                              )
                            : undefined
                        }
                        onClick={
                          runtimeLinks.length
                            ? (e) => e.stopPropagation()
                            : undefined
                        }
                      />
                    </TableCell>
                    <TableCell
                      className={`${COL_METRIC}`}
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
                    <TableCell className={`tabular-nums ${COL_SCORE}`}>
                      <ScoreRing value={s.pass_rate}>
                        {s.pass_rate == null
                          ? "—"
                          : `${(Number(s.pass_rate) * 100).toFixed(1)}%`}
                      </ScoreRing>
                    </TableCell>
                    <TableCell className={`tabular-nums ${COL_SCORE}`}>
                      <ScoreRing value={s.mean_score}>
                        {formatScore(s.mean_score)}
                      </ScoreRing>
                    </TableCell>
                    {show.has("pass_at_k") ? (
                      <TableCell className={`tabular-nums ${COL_SCORE}`}>
                        {atK.value == null ? (
                          "—"
                        ) : (
                          <HoverTip content={`pass@${atK.k}`}>
                            <ScoreRing value={atK.value}>
                              {formatPassMetric(atK.value)}
                              <span className="ml-1 text-mute">@{atK.k}</span>
                            </ScoreRing>
                          </HoverTip>
                        )}
                      </TableCell>
                    ) : null}
                    {show.has("pass_power_k") ? (
                      <TableCell className={`tabular-nums ${COL_SCORE}`}>
                        {powK.value == null ? (
                          "—"
                        ) : (
                          <HoverTip content={`pass^${powK.k}`}>
                            <ScoreRing value={powK.value}>
                              {formatPassMetric(powK.value)}
                              <span className="ml-1 text-mute">^{powK.k}</span>
                            </ScoreRing>
                          </HoverTip>
                        )}
                      </TableCell>
                    ) : null}
                    <TableCell className={`${COL_TEXT}`}>
                      <TruncateTip text={s.uploaded_by || ""} copyable />
                    </TableCell>
                    {show.has("suite_run_id") ? (
                      <TableCell className={`${COL_METRIC}`}>
                        <TruncateTip
                          text={shortSuiteId(s.suite_run_id)}
                          copyValue={s.suite_run_id}
                          copyable
                        />
                      </TableCell>
                    ) : null}
                  </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
