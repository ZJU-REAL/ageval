import { Liquid } from "liquid-gooey";

import { LiquidThumb, useTrackedRect } from "@/components/liquid-thumb";
import { liquidGroup } from "@/lib/liquid";
import {
  focusWithoutScroll,
  preventTabFocusScroll,
} from "@ageval/shared/scroll-port";
import { cn } from "@/lib/utils";
import { useRef } from "react";

type Item<T extends string> = { id: T; label: string };

export function PillTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  items: readonly Item<T>[];
  value: T;
  onChange: (id: T) => void;
  ariaLabel: string;
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
        "relative inline-flex shrink-0 rounded-[8px] bg-canvas p-0.5",
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
            "relative z-10 rounded-[8px] px-2.5 py-0.5 text-[11px]",
            "transition-colors duration-200 ease-smooth",
            value === item.id
              ? "font-medium text-ink"
              : "text-mute hover:bg-liquid-hover hover:text-ink",
          )}
        >
          {item.label}
        </button>
      ))}
    </Liquid>
  );
}
