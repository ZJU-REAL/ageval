import { Link } from "react-router-dom";

import { cn } from "@ageval/shared/lib/utils";

export type Crumb = { label: string; href?: string | null };

export function BreadcrumbNav({
  items,
  className,
}: {
  items: Crumb[];
  className?: string;
}) {
  return (
    <nav
      aria-label="Breadcrumb"
      className={cn("flex flex-wrap items-center gap-1.5 text-sm", className)}
    >
      {items.map((item, i) => {
        const last = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`} className="inline-flex items-center gap-1.5">
            {i > 0 && (
              <span className="text-mute select-none" aria-hidden>
                {">"}
              </span>
            )}
            {last || !item.href ? (
              <span
                className={cn(
                  last ? "text-ink font-medium" : "text-body",
                  "truncate max-w-[28ch]",
                )}
                aria-current={last ? "page" : undefined}
              >
                {item.label}
              </span>
            ) : (
              <Link
                to={item.href}
                className="text-body hover:text-ink truncate max-w-[28ch] transition-colors"
              >
                {item.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
