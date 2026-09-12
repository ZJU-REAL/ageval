import { useLayoutEffect, useMemo, useRef, useState } from "react";

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
  paretoFront,
  suiteChartPoint,
  type ParetoAxis,
} from "@/lib/leaderboard-charts";
import { useScatterMorph, type ScatterPose } from "@/lib/chart-morph";
import { markScaleForWidth, placeScatterLabels } from "@/lib/scatter-label-layout";
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

const DOT_STROKE = [
  "stroke-ink",
  "stroke-link",
  "stroke-nav-agents",
  "stroke-nav-datasets",
  "stroke-nav-plugins",
  "stroke-nav-models",
  "stroke-nav-inbox",
  "stroke-nav-orgs",
] as const;

const W = 1000;
const H = 520;
const L = 64;
const R = 80;
const T = 44;
const B = 80;
const PLOT_W = W - L - R;
const PLOT_H = H - T - B;

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

export function LeaderboardPareto({
  suites,
  axis,
  onOpenSuite,
  emptyTitle,
  emptyBody,
}: {
  suites: SuiteRow[];
  axis: ParetoAxis;
  onOpenSuite?: (suiteRunId: string | null) => void;
  emptyTitle?: string;
  emptyBody?: string;
}) {
  const pin = useMemo(() => loadModelPin(), []);
  const points = useMemo(
    () => suites.map((suite) => suiteChartPoint(suite, pin)),
    [suites, pin],
  );
  const plotted = useMemo(
    () => points.filter((p) => p.passRate != null && axisValue(p, axis) != null),
    [points, axis],
  );
  const hidden = points.length - plotted.length;
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const [cssW, setCssW] = useState(W);
  useLayoutEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    const apply = () => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setCssW(w);
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, [suites.length]);
  const unit = W / cssW;
  const mark = markScaleForWidth(cssW);
  const fontPx = mark.fontPx * unit;
  const dotR = mark.dotR * unit;
  const xs = plotted.map((p) => axisValue(p, axis) as number);
  const xmin = xs.length ? Math.min(...xs) * 0.7 : 0;
  const xmax = xs.length ? Math.max(...xs) * 1.15 || 1 : 1;
  const span = xmax - xmin || 1;
  const xOf = (v: number) => L + ((v - xmin) / span) * PLOT_W;
  const yOf = (v: number) => T + (1 - v) * PLOT_H;
  const front = useMemo(() => paretoFront(plotted, axis), [plotted, axis]);
  const frontIds = useMemo(
    () => new Set(front.map((p) => p.suite.suite_run_id)),
    [front],
  );
  const placedLabels = useMemo(() => {
    const xAt = (v: number) => L + ((v - xmin) / span) * PLOT_W;
    const yAt = (v: number) => T + (1 - v) * PLOT_H;
    return placeScatterLabels(
      plotted.map((p) => ({
        x: xAt(axisValue(p, axis) as number),
        y: yAt(p.passRate ?? 0),
        text: chartModelName(p.suite, pin),
      })),
      { left: L + 4, top: 8, right: W - 8, bottom: H - 36 },
      [],
      { unit, fontPx: mark.fontPx, dotR: mark.dotR },
    );
  }, [plotted, pin, axis, xmin, span, unit, mark.fontPx, mark.dotR]);
  const colorById = useMemo(() => {
    const m = new Map<string, number>();
    points.forEach((p, i) => m.set(p.suite.suite_run_id, i));
    return m;
  }, [points]);
  const targetPoses = useMemo((): ScatterPose[] => {
    return plotted.map((p, i) => {
      const placed = placedLabels[i];
      const xv = axisValue(p, axis) as number;
      return {
        id: p.suite.suite_run_id,
        colorIndex: colorById.get(p.suite.suite_run_id) ?? i,
        cx: xOf(xv),
        cy: yOf(p.passRate ?? 0),
        tx: placed?.tx ?? xOf(xv),
        ty: placed?.ty ?? yOf(p.passRate ?? 0) + 14,
        textAnchor: placed?.textAnchor ?? "middle",
        text: placed?.text ?? chartModelName(p.suite, pin),
        leader: placed?.leader ?? null,
        onFront: frontIds.has(p.suite.suite_run_id),
        opacity: 1,
      };
    });
  }, [plotted, placedLabels, axis, xmin, span, frontIds, pin, colorById]);
  const poses = useScatterMorph(targetPoses, axis);
  const poseById = useMemo(() => new Map(poses.map((p) => [p.id, p])), [poses]);
  const frontPath = useMemo(() => {
    const pts = poses.filter((p) => p.onFront).sort((a, b) => a.cx - b.cx);
    if (pts.length < 2) return "";
    return pts
      .map((p, i) => `${i ? "L" : "M"} ${p.cx.toFixed(1)} ${p.cy.toFixed(1)}`)
      .join(" ");
  }, [poses]);

  if (suites.length === 0) {
    return <EmptyBoard emptyTitle={emptyTitle} emptyBody={emptyBody} />;
  }

  const yTicks = [0, 0.2, 0.4, 0.6, 0.8, 1];
  const xTicks = [xmin, xmin + span / 2, xmax];
  const hovered = plotted.find((p) => p.suite.suite_run_id === hoveredId);
  const hoveredPose = hoveredId ? poseById.get(hoveredId) : undefined;
  const hx = hoveredPose?.cx ?? 0;
  const hy = hoveredPose?.cy ?? 0;
  const hoveredFill = hoveredPose
    ? DOT_FILL[hoveredPose.colorIndex % DOT_FILL.length]
    : DOT_FILL[0];
  const xAxisY = T + PLOT_H;
  const yAxisX = L;

  function poseOpacity(pose: ScatterPose): number {
    const hover =
      hoveredId == null ? (pose.onFront ? 1 : 0.4) : hoveredId === pose.id ? 1 : 0.2;
    return pose.opacity * hover;
  }

  return (
    <div className="space-y-3">
      <div className="blob-panel overflow-hidden p-2">
        <div
          ref={plotRef}
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
                fontSize={11}
                className={cn("fill-mute font-sans", hovered && "opacity-30")}
              >
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={t}
              x={xOf(t)}
              y={H - 28}
              textAnchor="middle"
              fontSize={11}
              className={cn("fill-mute font-sans", hovered && "opacity-30")}
            >
              {formatAxis(axis, t)}
            </text>
          ))}
          {frontPath ? (
            <path
              d={frontPath}
              fill="none"
              className="stroke-mute"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {poses.map((pose) => {
            if (!pose.leader) return null;
            const { leader } = pose;
            return (
              <g
                key={`${pose.id}-lead`}
                className="pointer-events-none"
                opacity={poseOpacity(pose)}
              >
                <line
                  x1={leader.x1}
                  y1={leader.y1}
                  x2={leader.x2}
                  y2={leader.y2}
                  className={DOT_STROKE[pose.colorIndex % DOT_STROKE.length]}
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
                <path
                  d={`M${leader.ax} ${leader.ay} L${leader.bx} ${leader.by} L${leader.cx} ${leader.cy} Z`}
                  className={DOT_FILL[pose.colorIndex % DOT_FILL.length]}
                />
              </g>
            );
          })}
          {poses.map((pose) => (
            <circle
              key={pose.id}
              cx={pose.cx}
              cy={pose.cy}
              r={dotR}
              opacity={poseOpacity(pose)}
              className={DOT_FILL[pose.colorIndex % DOT_FILL.length]}
            />
          ))}
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
                r={dotR}
                className={hoveredFill}
              />
              <text
                x={hx}
                y={H - 28}
                textAnchor="middle"
                fontSize={11}
                className="fill-ink stroke-canvas font-sans"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {formatAxis(axis, axisValue(hovered, axis) as number)}
              </text>
              <text
                x={L - 10}
                y={hy + 4}
                textAnchor="end"
                fontSize={11}
                className="fill-ink stroke-canvas font-sans"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {((hovered.passRate ?? 0) * 100).toFixed(1)}%
              </text>
            </g>
          ) : null}
          <text
            x={L + PLOT_W / 2}
            y={H - 8}
            textAnchor="middle"
            fontSize={12 * unit}
            className="fill-mute font-sans motion-safe:transition-opacity motion-safe:duration-200 motion-safe:ease-smooth"
          >
            {axisLabel(axis)}
          </text>
          <text
            x={18}
            y={T + PLOT_H / 2}
            textAnchor="middle"
            fontSize={12 * unit}
            className="fill-mute font-sans"
            transform={`rotate(-90 18 ${T + PLOT_H / 2})`}
          >
            Pass rate
          </text>
          {poses.map((pose) => (
            <text
              key={`${pose.id}-lab`}
              x={pose.tx}
              y={pose.ty}
              textAnchor={pose.textAnchor}
              fontSize={fontPx}
              opacity={poseOpacity(pose)}
              className="fill-body stroke-canvas font-sans"
              strokeWidth={3 * unit}
              paintOrder="stroke"
            >
              {pose.text}
            </text>
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0">
          {plotted.map((p) => {
            const labels = displayLabelsFromOverlay(p.suite.job_overlay);
            const harness = labels.agent || p.suite.agent_label || "—";
            const model = labels.model || p.suite.model_label || "—";
            const xv = axisValue(p, axis) as number;
            const pose = poseById.get(p.suite.suite_run_id);
            const left = (((pose?.cx ?? xOf(xv)) / W) * 100).toFixed(3);
            const top = (((pose?.cy ?? yOf(p.passRate ?? 0)) / H) * 100).toFixed(3);
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
        </div>
      </div>
      <p className="text-xs text-mute">
        {axis === "cost"
          ? hidden
            ? `${hidden} suite run${hidden === 1 ? " has" : "s have"} no cost (no agent cost and no catalog price). Hidden here. Switch to Tokens.`
            : "Left is cheaper. Cost is the sum of every job in the suite. When the agent did not report USD, the axis uses tokens × catalog price (estimated, not a billed invoice)."
          : "Left is cheaper / fewer. Cost and tokens are the sum of every job in the suite."}
      </p>
    </div>
  );
}
