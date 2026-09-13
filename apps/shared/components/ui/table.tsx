import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

export function Table({
  className,
  wrapClassName,
  ...props
}: React.HTMLAttributes<HTMLTableElement> & { wrapClassName?: string }) {
  return (
    <div className={cn("relative w-full overflow-auto", wrapClassName)}>
      <table
        className={cn("w-full table-fixed caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn(
        "bg-canvas-soft [&_tr]:border-b [&_tr]:bg-canvas-soft [&_tr]:hover:bg-canvas-soft",
        className,
      )}
      {...props}
    />
  );
}

export function TableBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />
  );
}

export function TableRow({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-hairline/50 transition-colors hover:bg-row-hover data-[state=selected]:bg-canvas-soft",
        className,
      )}
      {...props}
    />
  );
}

export function TableHead({
  className,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "h-10 bg-canvas-soft px-4 text-left align-middle text-sm font-medium text-mute whitespace-nowrap overflow-hidden text-ellipsis",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  className,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        "px-4 py-2.5 align-middle text-sm text-ink whitespace-nowrap overflow-hidden text-ellipsis",
        className,
      )}
      {...props}
    />
  );
}
