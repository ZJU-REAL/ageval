import type { ReactNode } from "react";

import { cn } from "@ageval/shared/lib/utils";

const SIZE = 16;
const STROKE = 2.5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * Observational 0–1 score as an IKB arc to the left of the number.
 * Fill is clamped to [0, 1]; missing values render the label only.
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
  const n = Number(value);
  const ratio =
    value == null || !Number.isFinite(n) || !(max > 0)
      ? null
      : Math.min(1, Math.max(0, n / max));

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
            className="stroke-link"
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
