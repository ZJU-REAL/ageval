import { useRef } from "react";
import { Liquid } from "liquid-gooey";

import { LiquidThumb, useTrackedRect } from "@/components/liquid-thumb";
import { liquidGroup } from "@/lib/liquid";
import {
  focusWithoutScroll,
  preventTabFocusScroll,
} from "@ageval/shared/lib/scroll-port";
import { cn } from "@/lib/utils";

type Item<T extends string> = { id: T; label: string };

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
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          data-tab-id={item.id}
          aria-selected={value === item.id}
          onMouseDown={preventTabFocusScroll}
          onClick={(e) => {
            focusWithoutScroll(e.currentTarget);
            onChange(item.id);
          }}
          className={cn(
            "relative z-10 rounded-[8px] text-sm font-medium",
            "transition-colors duration-200 ease-smooth",
            size === "sm" ? "px-2.5 py-1.5" : "px-3.5 py-1.5",
            value === item.id
              ? "font-semibold text-ink"
              : "text-mute hover:bg-liquid-hover hover:text-ink",
          )}
        >
          {item.label}
        </button>
      ))}
    </Liquid>
  );
}
