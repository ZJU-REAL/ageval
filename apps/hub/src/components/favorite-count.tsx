import { Star } from "lucide-react";

import { cn, formatCount } from "@ageval/shared/lib/utils";

export function FavoriteCount({
  count,
  compact = false,
  className,
}: {
  count?: number | null;
  compact?: boolean;
  className?: string;
}) {
  const n =
    Number.isFinite(count) && (count as number) > 0 ? Math.floor(count as number) : 0;
  const label = n === 1 ? "1 star" : `${formatCount(n)} stars`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 font-mono tabular-nums text-mute",
        compact ? "text-[11px]" : "text-xs",
        className,
      )}
      title={label}
      aria-label={label}
    >
      <Star
        className={compact ? "h-3 w-3" : "h-3.5 w-3.5"}
        strokeWidth={1.75}
        aria-hidden
      />
      <span aria-hidden>{formatCount(n)}</span>
    </span>
  );
}
