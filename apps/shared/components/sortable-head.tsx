import { useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { cn } from "@ageval/shared/lib/utils";

export type SortDir = "asc" | "desc" | null;

export function SortableHead({
  label,
  active,
  dir,
  onClick,
  className,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-start gap-1 p-0 text-left text-sm font-medium text-mute hover:text-ink transition-colors",
        className,
      )}
    >
      {label}
      {active && dir === "asc" ? (
        <ArrowUp className="h-3 w-3" />
      ) : active && dir === "desc" ? (
        <ArrowDown className="h-3 w-3" />
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-50" />
      )}
    </button>
  );
}

export function nextSort(
  currentKey: string | null,
  currentDir: SortDir,
  key: string,
): { key: string; dir: SortDir } {
  if (currentKey !== key) return { key, dir: "asc" };
  if (currentDir === "asc") return { key, dir: "desc" };
  if (currentDir === "desc") return { key, dir: null };
  return { key, dir: "asc" };
}

export function compareValues(a: unknown, b: unknown, dir: "asc" | "desc"): number {
  const mul = dir === "asc" ? 1 : -1;
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return (a - b) * mul;
  return String(a).localeCompare(String(b), undefined, { numeric: true }) * mul;
}

export function sortRows<T>(
  rows: readonly T[],
  key: string | null,
  dir: SortDir,
  value: (row: T, key: string) => unknown,
  fallback?: (a: T, b: T) => number,
): T[] {
  const list = [...rows];
  if (key && dir) {
    list.sort((a, b) => {
      const cmp = compareValues(value(a, key), value(b, key), dir);
      if (cmp !== 0) return cmp;
      return fallback ? fallback(a, b) : 0;
    });
  } else if (fallback) {
    list.sort(fallback);
  }
  return list;
}

export function useTableSort(
  initialKey: string | null = null,
  initialDir: SortDir = "asc",
) {
  const [sortKey, setSortKey] = useState<string | null>(initialKey);
  const [sortDir, setSortDir] = useState<SortDir>(initialDir);

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
  }

  function head(key: string, label: string, className?: string) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
        className={className}
      />
    );
  }

  return { sortKey, sortDir, setSortKey, setSortDir, onSort, head };
}
