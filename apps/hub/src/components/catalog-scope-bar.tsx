import type { ReactNode } from "react";

import { UnderlineTabs } from "@/components/underline-tabs";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type CatalogScope = "orgs" | "explore" | "favorites";

export const DATASET_SCOPE_ITEMS = [
  { id: "explore" as const, label: "Explore" },
  { id: "orgs" as const, label: "Your organizations" },
];

export const MARKETPLACE_SCOPE_ITEMS = [
  ...DATASET_SCOPE_ITEMS,
  { id: "favorites" as const, label: "Stars" },
];

function truthyParam(raw: string | null): boolean {
  const v = (raw || "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}

/** Hub list URL is the list filter: default Explore (`visibility=public`), `orgs=1`, `favorited=1`. */
export function catalogScopeFromSearch(
  params: URLSearchParams,
  allowFavorites = true,
): CatalogScope {
  if (
    allowFavorites &&
    (truthyParam(params.get("favorited")) || params.get("scope") === "favorites")
  ) {
    return "favorites";
  }
  if (params.get("orgs") === "1" || params.get("scope") === "orgs") {
    return "orgs";
  }
  return "explore";
}

export function catalogScopeSearch(scope: CatalogScope): Record<string, string> {
  if (scope === "favorites") return { favorited: "1" };
  if (scope === "orgs") return { orgs: "1" };
  return { visibility: "public" };
}

export function catalogListOpts(scope: CatalogScope): {
  orgs?: boolean;
  visibility?: "public";
  favorited?: boolean;
} {
  if (scope === "favorites") return { favorited: true };
  if (scope === "explore") return { visibility: "public" };
  return { orgs: true };
}

function CatalogSearch({
  query,
  onQuery,
  searchLabel,
  searchPlaceholder,
  hint,
  keyshortcuts,
}: {
  query: string;
  onQuery: (next: string) => void;
  searchLabel: string;
  searchPlaceholder: string;
  hint?: ReactNode;
  keyshortcuts?: string;
}) {
  const showHint = Boolean(hint) && !query;
  return (
    <div className="relative min-w-0 w-full max-w-sm">
      <Input
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder={showHint ? undefined : searchPlaceholder}
        aria-label={searchLabel}
        aria-keyshortcuts={keyshortcuts}
        className="min-w-0 w-full"
      />
      {showHint ? (
        <div className="pointer-events-none absolute inset-y-0 left-3.5 right-3.5 flex items-center gap-1.5 text-sm text-mute">
          <span className="min-w-0 truncate">{searchPlaceholder}</span>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function CatalogScopeBar<T extends string>({
  scope,
  onScope,
  items = [],
  query,
  onQuery,
  searchLabel,
  searchPlaceholder,
  searchHint,
  searchKeyshortcuts,
  end,
  variant = "tabs",
  className,
}: {
  scope?: T;
  onScope?: (next: T) => void;
  items?: readonly { id: T; label: string }[];
  query: string;
  onQuery: (next: string) => void;
  searchLabel: string;
  searchPlaceholder: string;
  /** Inside the field, right of the placeholder (e.g. ⌘F). Hidden while typing. */
  searchHint?: ReactNode;
  searchKeyshortcuts?: string;
  /** Trailing chrome on the search row. */
  end?: ReactNode;
  /** tabs = UnderlineTabs row above the search; group = hairline button group right of the search; select = Select right of the search; search = query box only. */
  variant?: "tabs" | "group" | "select" | "search";
  className?: string;
}) {
  const search = (
    <CatalogSearch
      query={query}
      onQuery={onQuery}
      searchLabel={searchLabel}
      searchPlaceholder={searchPlaceholder}
      hint={searchHint}
      keyshortcuts={searchKeyshortcuts}
    />
  );
  if (variant === "search") {
    return (
      <div className={cn("mb-4", className)}>
        <div className="flex items-center gap-2">
          {search}
          {end ? <div className="ml-auto shrink-0">{end}</div> : null}
        </div>
      </div>
    );
  }
  if (variant === "group") {
    return (
      <div className={cn("mb-4", className)}>
        <div className="flex items-center gap-2">
          {search}
          <div
            role="group"
            aria-label="Catalog scope"
            className="inline-flex shrink-0 items-center gap-0.5 rounded-[8px] border border-hairline p-0.5"
          >
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={scope === item.id}
                onClick={() => onScope?.(item.id)}
                className={cn(
                  "rounded-[6px] px-2.5 py-1 text-sm transition-colors duration-200 ease-smooth",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  scope === item.id
                    ? "bg-canvas-soft-2 text-ink"
                    : "text-body hover:bg-canvas-soft",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          {end ? <div className="ml-auto shrink-0">{end}</div> : null}
        </div>
      </div>
    );
  }
  if (variant === "select") {
    return (
      <div className={cn("mb-4", className)}>
        <div className="flex items-center gap-2">
          {search}
          <Select value={scope} onValueChange={(next) => onScope?.(next as T)}>
            <SelectTrigger aria-label="Catalog scope" className="shrink-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {items.map((item) => (
                <SelectItem key={item.id} value={item.id} mono={false}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {end ? <div className="ml-auto shrink-0">{end}</div> : null}
        </div>
      </div>
    );
  }
  return (
    <div className={cn("mb-4", className)}>
      <UnderlineTabs
        items={items}
        value={scope as T}
        onChange={onScope ?? (() => {})}
        ariaLabel="Catalog scope"
      />
      <div className="flex items-center gap-2 pt-3">
        {search}
        {end ? <div className="ml-auto shrink-0">{end}</div> : null}
      </div>
    </div>
  );
}
