import type { ReactNode } from "react";

import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { cn } from "@ageval/shared/lib/utils";

/** Bounded, sticky-header list used on Home and Leaderboard expand. */
export function ScrollTable({
  headers,
  rows,
  className,
}: {
  headers: string[];
  rows: Array<{
    key: string;
    onClick?: () => void;
    muted?: boolean;
    cells: ReactNode[];
  }>;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "blob-panel max-h-72 overflow-y-auto",
        className,
      )}
    >
      <table className="w-full caption-bottom text-sm">
        <TableHeader className="sticky top-0 z-10 bg-canvas-soft">
          <TableRow className="hover:bg-transparent">
            {headers.map((h) => (
              <TableHead key={h}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={row.key}
              className={cn(
                row.onClick && "cursor-pointer",
                row.muted && "opacity-70",
              )}
              onClick={row.onClick}
              tabIndex={row.onClick ? 0 : undefined}
              role={row.onClick ? "link" : undefined}
              onKeyDown={(e) => {
                if (!row.onClick) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  row.onClick();
                }
              }}
            >
              {row.cells.map((cell, i) => (
                <TableCell key={i} className="text-body">
                  {cell}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </table>
    </div>
  );
}
