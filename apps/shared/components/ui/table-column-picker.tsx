import { ChevronDown } from "lucide-react";

import { Button, SegmentedControl } from "@ageval/shared/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@ageval/shared/components/ui/dropdown-menu";
import { cn } from "@ageval/shared/lib/utils";

export type TableColumnOption<T extends string> = {
  id: T;
  label: string;
};

function toggleId<T extends string>(
  options: readonly TableColumnOption<T>[],
  value: readonly T[],
  id: T,
): T[] {
  const on = new Set(value);
  if (on.has(id)) on.delete(id);
  else on.add(id);
  return options.filter((opt) => on.has(opt.id)).map((opt) => opt.id);
}

/** Optional columns: one button group on md+, multi-select menu on small. */
export function TableColumnPicker<T extends string>({
  options,
  value,
  onChange,
  ariaLabel = "Optional columns",
  className,
}: {
  options: readonly TableColumnOption<T>[];
  value: readonly T[];
  onChange: (next: T[]) => void;
  ariaLabel?: string;
  className?: string;
}) {
  if (options.length === 0) return null;
  const selected = new Set(value);

  return (
    <div className={cn("flex shrink-0 items-center justify-end", className)}>
      <SegmentedControl
        label={ariaLabel}
        items={options}
        selected={(id) => selected.has(id)}
        onSelect={(id) => onChange(toggleId(options, value, id))}
        className="hidden h-9 md:inline-flex"
        itemClassName="h-full px-3"
      />
      <div className="md:hidden">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              className="h-9 gap-1 text-sm"
              aria-label={ariaLabel}
            >
              Columns
              <ChevronDown className="h-3.5 w-3.5 text-mute" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[10rem]">
            {options.map((opt) => (
              <DropdownMenuCheckboxItem
                key={opt.id}
                checked={selected.has(opt.id)}
                onCheckedChange={() =>
                  onChange(toggleId(options, value, opt.id))
                }
                onSelect={(event) => event.preventDefault()}
              >
                {opt.label}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
