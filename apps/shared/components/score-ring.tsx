import type { ReactNode } from "react";

import { cn } from "@ageval/shared/lib/utils";

const SIZE = 16;
const STROKE = 2.5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function scoreRatio(
  value: number | null | undefined,
  max: number,
): number | null {
  const n = Number(value);
  if (value == null || !Number.isFinite(n) || !(max > 0)) return null;
  return Math.min(1, Math.max(0, n / max));
}

/**
 * Linear mix from a pale link tint to solid theme blue.
 * Nearby scores stay apart, so one column reads as a range.
 */
function scoreInk(ratio: number): string {
  const strength = Math.round((0.2 + 0.8 * ratio) * 100);
  return `color-mix(in srgb, var(--color-link) ${strength}%, transparent)`;
}

/**
 * Observational 0–1 score as an IKB arc to the left of the number.
 * Arc length and ink both follow the score. Missing values render the label only.
 */
export function ScoreRing({
  value,
  max = 1,
  className,
  children,
}: {
  value: number | null | undefined;
  max?: number;
  className?: string;
  children: ReactNode;
}) {
  const ratio = scoreRatio(value, max);

  if (ratio == null) {
    return <span className={className}>{children}</span>;
  }

  const filled = ratio * CIRCUMFERENCE;

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="shrink-0 -rotate-90"
        aria-hidden
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          className="stroke-hairline"
          strokeWidth={STROKE}
        />
        {ratio > 0 ? (
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={scoreInk(ratio)}
            strokeWidth={STROKE}
            strokeDasharray={`${filled} ${CIRCUMFERENCE}`}
            strokeLinecap={ratio >= 1 ? "butt" : "round"}
          />
        ) : null}
      </svg>
      <span>{children}</span>
    </span>
  );
}

/**
 * Same 0–1 score as a near-rectangle. Length and ink both follow the score.
 * Missing values render the label only.
 */
export function ScoreBar({
  value,
  max = 1,
  className,
  children,
}: {
  value: number | null | undefined;
  max?: number;
  className?: string;
  children: ReactNode;
}) {
  const ratio = scoreRatio(value, max);
  if (ratio == null) {
    return <span className={className}>{children}</span>;
  }

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className="relative h-2.5 w-16 shrink-0 overflow-hidden rounded-[2px] border border-hairline"
        aria-hidden
      >
        <span
          className="absolute inset-y-0 left-0"
          style={{
            width: `${ratio * 100}%`,
            background: scoreInk(ratio),
          }}
        />
      </span>
      <span>{children}</span>
    </span>
  );
}
