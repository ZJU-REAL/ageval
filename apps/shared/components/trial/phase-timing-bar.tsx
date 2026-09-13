/**
 * Harbor-style horizontal phase / token bars with legend + hover labels.
 * Data from Attempt result.phase_timing / token_timing (#47 D).
 */

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@ageval/shared/components/ui/tooltip";

export type PhaseSeg = {
  id: string;
  label?: string;
  duration_ms?: number;
  tokens?: number;
};

export type PhaseTiming = {
  phases?: PhaseSeg[];
  total_ms?: number;
  started_at?: string | null;
  finished_at?: string | null;
};

export type TokenTiming = {
  segments?: PhaseSeg[];
  total_tokens?: number;
};

const PHASE_COLORS: Record<string, string> = {
  environment: "bg-[var(--viewer-phase-3)]",
  run: "bg-[var(--viewer-phase-1)]",
  evaluate: "bg-[var(--viewer-phase-2)]",
  record: "bg-[var(--viewer-phase-4)]",
  cleanup: "bg-[var(--viewer-phase-5)]",
};

const TOKEN_COLORS: Record<string, string> = {
  cached_input: "bg-[var(--viewer-phase-3)]",
  uncached_input: "bg-[var(--viewer-phase-1)]",
  output: "bg-[var(--viewer-phase-2)]",
};

function formatMs(ms: number | undefined | null): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return rem ? `${m}m ${String(rem).padStart(2, "0")}s` : `${m}m`;
}

function formatTokens(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(Math.round(n));
}

function colorFor(id: string, kind: "phase" | "token"): string {
  const map = kind === "phase" ? PHASE_COLORS : TOKEN_COLORS;
  return map[id] || "bg-[var(--viewer-phase-4)]";
}

function SegmentBar({
  title,
  segments,
  totalLabel,
  kind,
  valueKey,
  formatValue,
}: {
  title: string;
  segments: PhaseSeg[];
  totalLabel: string;
  kind: "phase" | "token";
  valueKey: "duration_ms" | "tokens";
  formatValue: (n: number | undefined) => string;
}) {
  const total = segments.reduce((acc, s) => acc + (Number(s[valueKey]) || 0), 0);
  if (total <= 0 && segments.length === 0) return null;

  const visible = segments.filter((seg) => {
    const v = Number(seg[valueKey]) || 0;
    return !(v <= 0 && total > 0);
  });

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-2">
        {/* Title + total on the left (Status-label style + value). */}
        <div className="flex items-baseline gap-2">
          <div className="text-xs text-mute">{title}</div>
          <span className="text-sm tabular text-ink">{totalLabel}</span>
        </div>
        <div
          className="flex h-3 w-full overflow-hidden rounded-[4px] bg-canvas-soft border border-hairline"
          role="img"
          aria-label={`${title}: ${totalLabel}`}
        >
          {segments.map((seg) => {
            const v = Number(seg[valueKey]) || 0;
            const pct = total > 0 ? (v / total) * 100 : 0;
            if (pct <= 0) return null;
            const label = seg.label || seg.id;
            return (
              <Tooltip key={seg.id}>
                <TooltipTrigger asChild>
                  <div
                    className={`${colorFor(seg.id, kind)} h-full min-w-[2px] cursor-default transition-opacity hover:opacity-90`}
                    style={{ width: `${pct}%` }}
                  />
                </TooltipTrigger>
                <TooltipContent side="top">
                  {label}: {formatValue(v)}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
        {/* Legend: labels only; values via Tooltip. */}
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
          {visible.map((seg) => {
            const v = Number(seg[valueKey]) || 0;
            const label = seg.label || seg.id;
            return (
              <li key={seg.id}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex cursor-default items-center gap-1.5 outline-none"
                    >
                      <span
                        className={`inline-block h-2 w-2 shrink-0 rounded-[2px] ${colorFor(seg.id, kind)}`}
                        aria-hidden
                      />
                      <span>{label}</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    {label}: {formatValue(v)}
                  </TooltipContent>
                </Tooltip>
              </li>
            );
          })}
        </ul>
      </div>
    </TooltipProvider>
  );
}

export function PhaseTimingBar({
  phaseTiming,
  tokenTiming,
}: {
  phaseTiming?: PhaseTiming | null;
  tokenTiming?: TokenTiming | null;
}) {
  const phases = phaseTiming?.phases || [];
  const tokens = (tokenTiming?.segments || []).filter((s) => (s.tokens ?? 0) > 0);

  if (phases.length === 0 && tokens.length === 0) return null;

  const both = tokens.length > 0 && phases.length > 0;

  return (
    <div
      className={
        both
          ? "flex flex-col gap-6 blob-panel p-4 sm:flex-row sm:items-stretch sm:gap-0"
          : "blob-panel p-4"
      }
    >
      {tokens.length > 0 ? (
        <div className={both ? "min-w-0 flex-1 sm:pr-6" : undefined}>
          <SegmentBar
            title="Tokens"
            segments={tokens}
            totalLabel={`${formatTokens(tokenTiming?.total_tokens)} tokens`}
            kind="token"
            valueKey="tokens"
            formatValue={formatTokens}
          />
        </div>
      ) : null}
      {phases.length > 0 ? (
        <div className={both ? "min-w-0 flex-1 sm:pl-6" : undefined}>
          <SegmentBar
            title="Timing"
            segments={phases}
            totalLabel={formatMs(phaseTiming?.total_ms)}
            kind="phase"
            valueKey="duration_ms"
            formatValue={formatMs}
          />
        </div>
      ) : null}
    </div>
  );
}
