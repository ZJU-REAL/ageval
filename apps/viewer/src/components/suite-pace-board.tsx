import { Info } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@ageval/shared/components/ui/tooltip";
import { formatDate, cn } from "@ageval/shared/lib/utils";
import {
  formatDurationMs,
  formatTimeLeft,
  suitePace,
  timeLeftNote,
  type PaceDot,
  type PaceTask,
  type PaceTone,
  type SuitePace,
} from "@/lib/suite-pace";

const MIN_GAP = 48;
const SCALE_MIN = 0.45;
const SCALE_MAX = 3.5;
const PAD_X = 20;
const H = 132;
const PAD_T = 14;
const PAD_B = 10;
const PLOT_H = H - PAD_T - PAD_B;

/** Even ticks in one unit, with the top a round step above the tallest task. */
function durationAxis(dataMaxMs: number): { top: number; step: number; ticks: number[] } {
  const peak = Math.max(dataMaxMs, 1);
  const steps = [
    500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000, 600_000,
    900_000, 1_800_000, 3_600_000, 7_200_000,
  ];
  let step = steps[steps.length - 1] ?? 60_000;
  let best = Infinity;
  for (const candidate of steps) {
    const intervals = Math.ceil(peak / candidate);
    if (intervals < 2 || intervals > 5) continue;
    const score = Math.abs(intervals - 4);
    if (score < best || (score === best && candidate > step)) {
      best = score;
      step = candidate;
    }
  }
  const top = Math.max(step, Math.ceil(peak / step) * step);
  const ticks: number[] = [];
  for (let value = 0; value <= top + step * 0.001; value += step) {
    ticks.push(Math.round(value));
  }
  return { top, step, ticks };
}

function axisLabel(ms: number, stepMs: number): string {
  if (ms === 0) {
    if (stepMs >= 3_600_000) return "0h";
    if (stepMs >= 60_000) return "0m";
    if (stepMs >= 1_000) return "0s";
    return "0ms";
  }
  return formatDurationMs(ms);
}

const TONE_DOT: Record<PaceTone, string> = {
  pass: "bg-nav-home",
  fail: "bg-error",
  error: "bg-warning",
  forecast: "border border-mute bg-canvas",
};

function toneLabel(tone: PaceTone): string {
  if (tone === "pass") return "Pass";
  if (tone === "fail") return "Fail";
  if (tone === "error") return "Error";
  return "Not started";
}

type Placed = PaceDot & { x: number; y: number };

function smoothPath(points: Placed[]): string {
  if (points.length < 2) return "";
  const start = points[0];
  if (!start) return "";
  let d = `M${start.x.toFixed(1)} ${start.y.toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    if (!p0 || !p1 || !p2 || !p3) continue;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

function gapPx(prev: PaceDot, next: PaceDot, gapMs: number | null, scale: number): number {
  const min = MIN_GAP * scale;
  const max = min * 3;
  if (prev.finishedAt == null || next.finishedAt == null || gapMs == null || gapMs <= 0) {
    return min;
  }
  const dt = next.finishedAt - prev.finishedAt;
  if (dt <= 0) return min;
  return Math.max(min, Math.min(max, (dt / gapMs) * min));
}

function yOf(ms: number, top: number): number {
  return PAD_T + PLOT_H - (ms / top) * PLOT_H;
}

function place(
  pace: SuitePace,
  scale: number,
): {
  marks: Placed[];
  width: number;
  axis: { top: number; step: number; ticks: number[] };
} {
  const all = [...pace.dots, ...pace.forecast];
  const peak = Math.max(...all.map((dot) => dot.durationMs), 1);
  const axis = durationAxis(peak);
  let x = PAD_X;
  const marks: Placed[] = [];
  all.forEach((dot, index) => {
    const prev = all[index - 1];
    if (prev) x += gapPx(prev, dot, pace.gapMs, scale);
    marks.push({ ...dot, x, y: yOf(dot.durationMs, axis.top) });
  });
  return { marks, width: Math.max(x + PAD_X, PAD_X * 2), axis };
}

function TimeLeftInfo({ pace }: { pace: SuitePace }) {
  return (
    <TooltipProvider delayDuration={80}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            aria-label="How time left is estimated"
          >
            <Info className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left" className="max-w-xs px-3 py-2 text-sm leading-5">
          {timeLeftNote(pace)}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function clampScale(value: number): number {
  return Math.min(SCALE_MAX, Math.max(SCALE_MIN, value));
}

function DurationScroll({
  pace,
  onOpenTask,
}: {
  pace: SuitePace;
  onOpenTask: (taskId: string) => void;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickToEnd = useRef(true);
  const desiredScale = useRef(1);
  const [gapScale, setGapScale] = useState(1);
  const pendingZoom = useRef<{ unit: number; viewX: number } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number } | null>(null);
  const suppressClick = useRef(false);
  const { marks, width, axis } = useMemo(() => place(pace, gapScale), [pace, gapScale]);
  const history = marks.filter((mark) => mark.tone !== "forecast");
  const forecast = marks.filter((mark) => mark.tone === "forecast");
  const historyPath = smoothPath(history);
  const forecastPath = smoothPath(
    forecast.length && history.length ? [history[history.length - 1] as Placed, ...forecast] : [],
  );

  const applyZoom = (clientX: number, factor: number) => {
    const el = scrollerRef.current;
    if (!el || !Number.isFinite(factor) || factor <= 0) return;
    const next = clampScale(desiredScale.current * factor);
    if (next === desiredScale.current) return;
    const rect = el.getBoundingClientRect();
    const viewX = clientX - rect.left;
    pendingZoom.current = { unit: (el.scrollLeft + viewX) / gapScale, viewX };
    desiredScale.current = next;
    setGapScale(next);
  };
  const applyZoomRef = useRef(applyZoom);
  applyZoomRef.current = applyZoom;

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const pending = pendingZoom.current;
    if (pending) {
      el.scrollLeft = pending.unit * gapScale - pending.viewX;
      pendingZoom.current = null;
      stickToEnd.current = el.scrollLeft + el.clientWidth >= el.scrollWidth - 8;
      return;
    }
    if (stickToEnd.current) el.scrollLeft = el.scrollWidth;
  }, [width, gapScale]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.01);
      applyZoomRef.current(event.clientX, factor);
    };
    const gestureOrigin = { scale: 1 };
    const onGestureStart = (event: Event) => {
      event.preventDefault();
      gestureOrigin.scale = desiredScale.current;
    };
    const onGestureChange = (event: Event) => {
      event.preventDefault();
      const gesture = event as Event & { scale?: number; clientX?: number };
      if (typeof gesture.scale !== "number" || gesture.scale <= 0) return;
      const next = clampScale(gestureOrigin.scale * gesture.scale);
      const from = desiredScale.current;
      if (next === from) return;
      const clientX =
        typeof gesture.clientX === "number"
          ? gesture.clientX
          : el.getBoundingClientRect().left + el.clientWidth / 2;
      applyZoomRef.current(clientX, next / from);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("gesturestart", onGestureStart);
    el.addEventListener("gesturechange", onGestureChange);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("gesturestart", onGestureStart);
      el.removeEventListener("gesturechange", onGestureChange);
    };
  }, []);

  return (
    <div className="mt-3 flex items-end">
      <div className="relative h-[132px] w-14 shrink-0">
        {axis.ticks.map((tick) => (
          <span
            key={tick}
            className="absolute right-2 -translate-y-1/2 font-mono text-xs text-mute tabular-nums"
            style={{ top: yOf(tick, axis.top) }}
          >
            {axisLabel(tick, axis.step)}
          </span>
        ))}
      </div>
      <div
        ref={scrollerRef}
        className="min-w-0 flex-1 touch-pan-x overflow-x-auto border-b border-hairline"
        aria-label="Task durations. Pinch to change the spacing."
        onPointerDown={(event) => {
          const el = event.currentTarget;
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointers.current.size < 2) return;
          for (const id of pointers.current.keys()) el.setPointerCapture(id);
          const pair = [...pointers.current.values()];
          const a = pair[0];
          const b = pair[1];
          if (!a || !b) return;
          pinch.current = { dist: Math.hypot(a.x - b.x, a.y - b.y) };
        }}
        onPointerMove={(event) => {
          if (!pointers.current.has(event.pointerId)) return;
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointers.current.size < 2 || !pinch.current) return;
          const pair = [...pointers.current.values()];
          const a = pair[0];
          const b = pair[1];
          if (!a || !b) return;
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (pinch.current.dist < 8 || dist < 8) {
            pinch.current = { dist };
            return;
          }
          const factor = dist / pinch.current.dist;
          pinch.current = { dist };
          suppressClick.current = true;
          applyZoom((a.x + b.x) / 2, factor);
        }}
        onPointerUp={(event) => {
          pointers.current.delete(event.pointerId);
          if (pointers.current.size < 2) pinch.current = null;
        }}
        onPointerCancel={(event) => {
          pointers.current.delete(event.pointerId);
          pinch.current = null;
        }}
        onScroll={(event) => {
          const el = event.currentTarget;
          stickToEnd.current = el.scrollLeft + el.clientWidth >= el.scrollWidth - 8;
        }}
      >
        <div className="relative" style={{ width, height: H }}>
        <svg
          width={width}
          height={H}
          viewBox={`0 0 ${width} ${H}`}
          className="pointer-events-none block"
          role="img"
          aria-label="Task durations. Pinch to change the spacing. Newest at the right."
        >
          {axis.ticks.map((tick) => (
            <line
              key={tick}
              x1={0}
              x2={width}
              y1={yOf(tick, axis.top)}
              y2={yOf(tick, axis.top)}
              className="stroke-hairline"
              strokeWidth={1}
            />
          ))}
          {historyPath ? (
            <path
              d={historyPath}
              fill="none"
              className="stroke-body"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : null}
          {forecastPath ? (
            <path
              d={forecastPath}
              fill="none"
              className="stroke-link"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray="4 4"
            />
          ) : null}
        </svg>
        <TooltipProvider delayDuration={200}>
          {marks.map((mark) => {
            const openable = mark.tone !== "forecast";
            return (
              <Tooltip key={`${mark.tone}-${mark.taskId}`}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className={cn(
                      "absolute z-10 flex size-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                      openable ? "cursor-pointer" : "cursor-default",
                    )}
                    style={{ left: mark.x, top: mark.y }}
                    aria-label={
                      openable
                        ? `${mark.taskId}, ${formatDurationMs(mark.durationMs)}, ${toneLabel(mark.tone)}`
                        : `${mark.taskId}, not started`
                    }
                    onClick={() => {
                      if (suppressClick.current) {
                        suppressClick.current = false;
                        return;
                      }
                      if (openable) onOpenTask(mark.taskId);
                    }}
                  >
                    <span className={cn("size-2 rounded-full", TONE_DOT[mark.tone])} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs px-3 py-2 text-sm leading-5">
                  <span className="block font-medium text-ink">{mark.taskId}</span>
                  <span className="block text-body">{toneLabel(mark.tone)}</span>
                  <span className="block font-mono tabular-nums text-ink">
                    {mark.tone === "forecast"
                      ? `about ${formatDurationMs(mark.durationMs)}`
                      : formatDurationMs(mark.durationMs)}
                  </span>
                  {mark.finishedAt != null ? (
                    <span className="block text-mute">{formatDate(mark.finishedAt)}</span>
                  ) : null}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </TooltipProvider>
        </div>
      </div>
    </div>
  );
}

/** Finished/total and time left, above a suite's task table. */
export function SuitePaceBoard({
  tasks,
  onOpenTask,
}: {
  tasks: PaceTask[];
  onOpenTask: (taskId: string) => void;
}) {
  const pace = useMemo(() => suitePace(tasks), [tasks]);
  const showChart = pace.dots.length > 0 || pace.forecast.length > 0;

  return (
    <section className="blob-panel p-4" aria-label="Suite progress">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-body">Tasks</p>
          <p className="figure font-mono tabular-nums text-ink">
            {pace.done}/{pace.total}
          </p>
        </div>
        <div className="text-right">
          <div className="flex items-center justify-end">
            <p className="text-sm text-body">Time left</p>
            <TimeLeftInfo pace={pace} />
          </div>
          <p className="figure font-mono tabular-nums text-ink">{formatTimeLeft(pace)}</p>
        </div>
      </div>
      {showChart ? <DurationScroll pace={pace} onOpenTask={onOpenTask} /> : null}
    </section>
  );
}
