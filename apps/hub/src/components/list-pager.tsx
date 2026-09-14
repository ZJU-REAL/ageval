import { Button } from "@ageval/shared/components/ui/button";

export function ListPager({
  offset,
  limit,
  total,
  busy = false,
  onOffset,
}: {
  offset: number;
  limit: number;
  total: number;
  busy?: boolean;
  onOffset: (next: number) => void;
}) {
  if (total <= limit) return null;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  const prev = Math.max(0, offset - limit);
  const next = offset + limit;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 pt-3">
      <p className="font-mono text-xs tabular-nums text-mute">
        {start}–{end} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || offset <= 0}
          onClick={() => onOffset(prev)}
        >
          Previous
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || next >= total}
          onClick={() => onOffset(next)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
