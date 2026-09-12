import { useRef } from "react";
import { Liquid } from "liquid-gooey";
import type { LucideIcon } from "lucide-react";

import type { NavGlyph } from "@/components/empty-state";
import { LiquidThumb, useTrackedRect } from "@/components/liquid-thumb";
import { liquidGroup } from "@/lib/liquid";
import { cn } from "@/lib/utils";

type Item<T extends string> = {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Sidebar glyph token: paints the icon only (`nav-*`), not the label. */
  glyph?: NavGlyph;
  /** Applied to the icon only (selected / hover tone). Label stays body/mute. */
  iconClassName?: string;
};

export function UnderlineTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  size = "md",
  className,
}: {
  items: readonly Item<T>[];
  value: T;
  onChange: (id: T) => void;
  ariaLabel: string;
  size?: "md" | "sm";
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const itemsKey = items.map((item) => item.id).join("\0");
  const { bar, ready } = useTrackedRect(
    listRef,
    '[aria-selected="true"]',
    `${value}\0${itemsKey}`,
  );

  return (
    <Liquid
      ref={listRef}
      {...liquidGroup}
      fill="var(--viewer-canvas-soft-2)"
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "relative inline-flex flex-wrap gap-0.5 rounded-[8px] bg-canvas p-1",
        className,
      )}
    >
      <LiquidThumb bar={bar} ready={ready} />
      {items.map((item) => {
        const selected = value === item.id;
        const Icon = item.icon;
        const toneIcon = Boolean(item.iconClassName);
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            data-tab-id={item.id}
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={cn(
              "group relative z-10 inline-flex items-center gap-1.5 rounded-[8px] text-sm font-medium",
              "transition-colors duration-200 ease-smooth",
              size === "sm" ? "px-2.5 py-1.5" : "px-3.5 py-1.5",
              selected
                ? cn("font-semibold", toneIcon ? "text-body" : "text-ink")
                : cn(
                    "text-mute hover:bg-liquid-hover",
                    toneIcon ? "hover:text-body" : "hover:text-ink",
                  ),
            )}
          >
            {Icon ? (
              item.glyph ? (
                <span data-nav-glyph={item.glyph} className="inline-flex shrink-0">
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
              ) : (
                <Icon
                  strokeWidth={selected ? 2.5 : 2}
                  className={cn(
                    "size-4 shrink-0 transition-[color,stroke-width] duration-200 ease-smooth",
                    item.iconClassName,
                  )}
                  aria-hidden
                />
              )
            ) : null}
            {item.label}
          </button>
        );
      })}
    </Liquid>
  );
}
