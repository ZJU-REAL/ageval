import { DownloadCount } from "@/components/download-count";
import { FavoriteCount } from "@/components/favorite-count";
import { cn } from "@ageval/shared/lib/utils";

export function MarketplaceCounts({
  downloadCount,
  favoriteCount,
  compact = false,
  className,
}: {
  downloadCount?: number | null;
  favoriteCount?: number | null;
  compact?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <DownloadCount count={downloadCount} compact={compact} />
      <FavoriteCount count={favoriteCount} compact={compact} />
    </span>
  );
}
