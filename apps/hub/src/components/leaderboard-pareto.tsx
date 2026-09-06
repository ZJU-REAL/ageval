import { useMemo, useState } from "react";

import { HoverTip } from "@/components/hover-tip";
import {
  joinOverlay,
  loadModelPin,
  pinnedModel,
  type ModelPin,
} from "@/lib/model-pin";
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

const DOT_FILL = [
  "fill-ink",
  "fill-link",
  "fill-nav-agents",
  "fill-nav-datasets",
  "fill-nav-plugins",
  "fill-nav-models",
  "fill-nav-inbox",
  "fill-nav-orgs",
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
  if (axis === "cost") return "Suite cost";
  if (axis === "tokens") return "Suite tokens";
  return "Suite time";
}

function chartModelName(suite: SuiteRow, pin: ModelPin): string {
  const overlay =
    displayLabelsFromOverlay(suite.job_overlay).model || suite.model_label || "";
  const pretty = pinnedModel(joinOverlay(overlay, pin).canonical, pin)?.name;
  if (pretty) return pretty;
  const trimmed = overlay.trim();
  if (!trimmed) return "—";
  const slash = trimmed.lastIndexOf("/");
  return slash >= 0 ? trimmed.slice(slash + 1) : trimmed;
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
  const [hoveredId, setHoveredId] = useState<string | null>(null);

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
  const L = 64;
  const R = 28;
  const T = 44;
  const B = 56;
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
  const hoveredIndex = plotted.findIndex((p) => p.suite.suite_run_id === hoveredId);
  const hovered = hoveredIndex >= 0 ? plotted[hoveredIndex] : null;
  const hx = hovered ? xOf(axisValue(hovered, axis) as number) : 0;
  const hy = hovered ? yOf(hovered.passRate ?? 0) : 0;
  const xAxisY = T + plotH;
  const yAxisX = L;

  return (
    <div className="space-y-3">
      <div className="blob-panel overflow-hidden p-2">
        <div
          className="relative mx-auto w-full max-h-[min(62vh,32rem)]"
          style={{ aspectRatio: `${W} / ${H}` }}
          onPointerLeave={() => setHoveredId(null)}
        >
        <svg
          className="absolute inset-0 h-full w-full"
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
                x={L - 10}
                y={yOf(t) + 4}
                textAnchor="end"
                className={cn(
                  "fill-mute text-[11px]",
                  hovered && "opacity-30",
                )}
              >
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={t}
              x={xOf(t)}
              y={H - 22}
              textAnchor="middle"
              className={cn("fill-mute text-[11px]", hovered && "opacity-30")}
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
              opacity={hovered ? 0.25 : 1}
            />
          ) : null}
          {plotted.map((p, i) => {
            const xv = axisValue(p, axis) as number;
            const cx = xOf(xv);
            const cy = yOf(p.passRate ?? 0);
            const open = openSuiteId === p.suite.suite_run_id;
            const dim = hoveredId != null && hoveredId !== p.suite.suite_run_id;
            return (
              <circle
                key={p.suite.suite_run_id}
                cx={cx}
                cy={cy}
                r={4}
                className={cn(
                  DOT_FILL[i % DOT_FILL.length],
                  "motion-safe:transition-opacity motion-safe:duration-200 motion-safe:ease-smooth",
                  dim && "opacity-20",
                  open && "stroke-link",
                )}
                strokeWidth={open ? 2 : 0}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
          {hovered ? (
            <g className="pointer-events-none">
              <line
                x1={hx}
                x2={hx}
                y1={hy}
                y2={xAxisY}
                className="stroke-ink"
                strokeWidth={1}
                strokeDasharray="5 4"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={yAxisX}
                x2={hx}
                y1={hy}
                y2={hy}
                className="stroke-ink"
                strokeWidth={1}
                strokeDasharray="5 4"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={hx}
                x2={hx}
                y1={xAxisY}
                y2={xAxisY + 6}
                className="stroke-ink"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={yAxisX - 6}
                x2={yAxisX}
                y1={hy}
                y2={hy}
                className="stroke-ink"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
              <circle
                cx={hx}
                cy={hy}
                r={4}
                className={DOT_FILL[hoveredIndex % DOT_FILL.length]}
              />
              <text
                x={hx}
                y={H - 22}
                textAnchor="middle"
                className="fill-ink stroke-canvas text-[11px]"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {formatAxis(axis, axisValue(hovered, axis) as number)}
              </text>
              <text
                x={L - 10}
                y={hy + 4}
                textAnchor="end"
                className="fill-ink stroke-canvas text-[11px]"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {((hovered.passRate ?? 0) * 100).toFixed(1)}%
              </text>
            </g>
          ) : null}
          <text
            x={L + plotW / 2}
            y={H - 4}
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
              y={T - 14}
              textAnchor="end"
              className="fill-link text-[11px]"
            >
              most efficient →
            </text>
          ) : null}
        </svg>
        <div className="pointer-events-none absolute inset-0">
          {plotted.map((p) => {
            const labels = displayLabelsFromOverlay(p.suite.job_overlay);
            const harness = labels.agent || p.suite.agent_label || "—";
            const model = labels.model || p.suite.model_label || "—";
            const xv = axisValue(p, axis) as number;
            const left = ((xOf(xv) / W) * 100).toFixed(3);
            const top = ((yOf(p.passRate ?? 0) / H) * 100).toFixed(3);
            const resource = formatAxis(axis, xv);
            return (
              <HoverTip
                key={p.suite.suite_run_id}
                content={
                  <span className="break-normal">
                    <span className="block font-medium">
                      {harness} / {model}
                    </span>
                    <span className="block">
                      {((p.passRate ?? 0) * 100).toFixed(1)}% · {resource}
                    </span>
                    <span className="text-mute">Click to open suite run</span>
                  </span>
                }
              >
                <button
                  type="button"
                  className={cn(
                    "pointer-events-auto absolute h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  )}
                  style={{ left: `${left}%`, top: `${top}%` }}
                  aria-label={`${harness} ${model}. Click to open suite run`}
                  onPointerEnter={() => setHoveredId(p.suite.suite_run_id)}
                  onPointerLeave={() =>
                    setHoveredId((cur) =>
                      cur === p.suite.suite_run_id ? null : cur,
                    )
                  }
                  onFocus={() => setHoveredId(p.suite.suite_run_id)}
                  onBlur={() =>
                    setHoveredId((cur) =>
                      cur === p.suite.suite_run_id ? null : cur,
                    )
                  }
                  onClick={() => onOpenSuite?.(p.suite.suite_run_id)}
                />
              </HoverTip>
            );
          })}
        </div>
        {plotted.map((p) => {
          const xv = axisValue(p, axis) as number;
          const left = ((xOf(xv) / W) * 100).toFixed(3);
          const top = ((yOf(p.passRate ?? 0) / H) * 100).toFixed(3);
          const dim = hoveredId != null && hoveredId !== p.suite.suite_run_id;
          return (
            <div
              key={`${p.suite.suite_run_id}-lab`}
              className={cn(
                "pointer-events-none absolute max-w-[9rem] truncate text-center text-[11px] leading-4 text-body",
                "motion-safe:transition-opacity motion-safe:duration-200 motion-safe:ease-smooth",
                dim && "opacity-20",
              )}
              style={{
                left: `${left}%`,
                top: `${top}%`,
                transform: "translate(-50%, calc(-100% - 8px))",
              }}
            >
              {chartModelName(p.suite, pin)}
            </div>
          );
        })}
        </div>
      </div>
      <p className="text-xs text-mute">
        {axis === "cost"
          ? hidden
            ? `${hidden} suite run${hidden === 1 ? " has" : "s have"} no cost (no agent cost and no catalog price). Hidden here. Switch to Tokens.`
            : "Cost is the sum of every job in the suite. When the agent did not report USD, the axis uses tokens × catalog price (estimated, not a billed invoice)."
          : "Right is cheaper / fewer. Solid line is the Pareto front. Metrics are observational, not a suite PASS. Cost and tokens are the sum of every job in the suite."}
      </p>
    </div>
  );
}
