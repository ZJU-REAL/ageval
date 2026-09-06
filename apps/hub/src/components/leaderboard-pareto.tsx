import { useMemo } from "react";

import { HoverTip } from "@/components/hover-tip";
import { loadModelPin } from "@/lib/model-pin";
import type { SuiteRow } from "@/lib/api";
import {
  axisValue,
  formatDurationS,
  formatTokenCount,
  formatUsd,
  suiteChartPoint,
  type ParetoAxis,
  type SuiteChartPoint,
} from "@/lib/leaderboard-charts";
import { cn, displayLabelsFromOverlay } from "@/lib/utils";

const DOT_CLASS = [
  "bg-ink",
  "bg-link",
  "bg-nav-agents",
  "bg-nav-datasets",
  "bg-nav-plugins",
  "bg-nav-models",
  "bg-nav-inbox",
  "bg-nav-orgs",
] as const;

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

function formatAxis(axis: ParetoAxis, n: number): string {
  if (axis === "cost") return formatUsd(n);
  if (axis === "tokens") return formatTokenCount(n);
  return formatDurationS(n);
}

function axisLabel(axis: ParetoAxis): string {
  if (axis === "cost") return "Avg cost per suite";
  if (axis === "tokens") return "Total tokens";
  return "Wall time";
}

function paretoFront(points: SuiteChartPoint[], axis: ParetoAxis): SuiteChartPoint[] {
  const usable = points
    .filter((p) => p.passRate != null && axisValue(p, axis) != null)
    .sort((a, b) => (axisValue(a, axis) ?? 0) - (axisValue(b, axis) ?? 0));
  const front: SuiteChartPoint[] = [];
  let bestY = Number.NEGATIVE_INFINITY;
  for (const p of usable) {
    const y = p.passRate ?? 0;
    if (y >= bestY) {
      front.push(p);
      bestY = y;
    }
  }
  return front;
}

export function LeaderboardPareto({
  suites,
  axis,
  openSuiteId,
  onOpenSuite,
  emptyTitle,
  emptyBody,
}: {
  suites: SuiteRow[];
  axis: ParetoAxis;
  openSuiteId?: string | null;
  onOpenSuite?: (suiteRunId: string | null) => void;
  emptyTitle?: string;
  emptyBody?: string;
}) {
  const pin = useMemo(() => loadModelPin(), []);
  const points = useMemo(
    () => suites.map((suite) => suiteChartPoint(suite, pin)),
    [suites, pin],
  );
  const plotted = points.filter(
    (p) => p.passRate != null && axisValue(p, axis) != null,
  );
  const hidden = points.length - plotted.length;

  if (suites.length === 0) {
    return <EmptyBoard emptyTitle={emptyTitle} emptyBody={emptyBody} />;
  }

  const xs = plotted.map((p) => axisValue(p, axis) as number);
  const xmin = xs.length ? Math.min(...xs) * 0.7 : 0;
  const xmax = xs.length ? Math.max(...xs) * 1.15 || 1 : 1;
  const span = xmax - xmin || 1;
  const front = paretoFront(plotted, axis);
  const W = 1000;
  const H = 520;
  const L = 56;
  const R = 28;
  const T = 28;
  const B = 48;
  const plotW = W - L - R;
  const plotH = H - T - B;
  const xOf = (v: number) => L + (1 - (v - xmin) / span) * plotW;
  const yOf = (v: number) => T + (1 - v) * plotH;
  const yTicks = [0, 0.2, 0.4, 0.6, 0.8, 1];
  const xTicks = [xmax, xmin + span / 2, xmin];
  const frontPath = [...front]
    .sort((a, b) => (axisValue(b, axis) ?? 0) - (axisValue(a, axis) ?? 0))
    .map((p, i) => {
      const x = xOf(axisValue(p, axis) as number);
      const y = yOf(p.passRate ?? 0);
      return `${i ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="space-y-3">
      <div className="blob-panel overflow-hidden p-2">
        <div className="relative">
        <svg
          className="block h-[min(62vh,32rem)] w-full"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Pass rate versus ${axisLabel(axis)}`}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line
                x1={L}
                x2={W - R}
                y1={yOf(t)}
                y2={yOf(t)}
                className="stroke-hairline"
                strokeWidth={1}
              />
              <text
                x={L - 8}
                y={yOf(t) + 4}
                textAnchor="end"
                className="fill-mute text-[11px]"
              >
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={t}
              x={xOf(t)}
              y={H - 18}
              textAnchor="middle"
              className="fill-mute text-[11px]"
            >
              {formatAxis(axis, t)}
            </text>
          ))}
          {frontPath ? (
            <path
              d={frontPath}
              fill="none"
              className="stroke-ink"
              strokeWidth={1.5}
            />
          ) : null}
          <text
            x={L + plotW / 2}
            y={H - 2}
            textAnchor="middle"
            className="fill-mute text-[11px]"
          >
            {axisLabel(axis)}
          </text>
          <text
            x={16}
            y={T + plotH / 2}
            textAnchor="middle"
            className="fill-mute text-[11px]"
            transform={`rotate(-90 16 ${T + plotH / 2})`}
          >
            Pass rate
          </text>
          {plotted.length ? (
            <text
              x={W - R}
              y={T - 8}
              textAnchor="end"
              className="fill-link text-[11px]"
            >
              most efficient →
            </text>
          ) : null}
        </svg>
        <div className="pointer-events-none absolute inset-0">
          {plotted.map((p, i) => {
            const labels = displayLabelsFromOverlay(p.suite.job_overlay);
            const harness = labels.agent || p.suite.agent_label || "—";
            const model = labels.model || p.suite.model_label || "—";
            const xv = axisValue(p, axis) as number;
            const left = ((xOf(xv) / W) * 100).toFixed(3);
            const top = ((yOf(p.passRate ?? 0) / H) * 100).toFixed(3);
            const open = openSuiteId === p.suite.suite_run_id;
            const resource = formatAxis(axis, xv);
            const costNote =
              axis === "cost" && p.costSource === "estimated" ? " · est." : "";
            return (
              <HoverTip
                key={p.suite.suite_run_id}
                content={
                  <span>
                    <span className="block font-medium">
                      {harness} / {model}
                    </span>
                    <span className="block">
                      {((p.passRate ?? 0) * 100).toFixed(1)}% pass · {resource}
                      {costNote}
                    </span>
                    <span className="text-mute">Click to open suite run</span>
                  </span>
                }
              >
                <button
                  type="button"
                  className={cn(
                    "pointer-events-auto absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
                    DOT_CLASS[i % DOT_CLASS.length],
                    p.costSource === "estimated" &&
                      axis === "cost" &&
                      "ring-1 ring-hairline-strong",
                    open && "ring-2 ring-link/70",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  )}
                  style={{ left: `${left}%`, top: `${top}%` }}
                  aria-label={`${harness} ${model}. Click to open suite run`}
                  onClick={() => onOpenSuite?.(p.suite.suite_run_id)}
                />
              </HoverTip>
            );
          })}
        </div>
        {plotted.map((p) => {
          const labels = displayLabelsFromOverlay(p.suite.job_overlay);
          const model = labels.model || p.suite.model_label || "";
          const harness = labels.agent || p.suite.agent_label || "";
          const xv = axisValue(p, axis) as number;
          const left = ((xOf(xv) / W) * 100).toFixed(3);
          const top = ((yOf(p.passRate ?? 0) / H) * 100).toFixed(3);
          return (
            <div
              key={`${p.suite.suite_run_id}-lab`}
              className="pointer-events-none absolute text-[11px] leading-4 text-body"
              style={{
                left: `calc(${left}% + 10px)`,
                top: `calc(${top}% - 18px)`,
              }}
            >
              <div>{model}</div>
              <div className="text-mute">
                {harness}
                {axis === "cost" && p.costSource === "estimated" ? " · est." : ""}
              </div>
            </div>
          );
        })}
        </div>
      </div>
      <p className="text-xs text-mute">
        {axis === "cost"
          ? hidden
            ? `${hidden} suite run${hidden === 1 ? " has" : "s have"} no cost (no agent cost and no catalog price). Hidden here. Switch to Tokens.`
            : "Cost uses reported USD when the agent sent it. Otherwise token × catalog price (est.). Not a billed invoice."
          : "Right is cheaper / fewer. Solid line is the Pareto front. Metrics are observational, not a suite PASS."}
      </p>
    </div>
  );
}
