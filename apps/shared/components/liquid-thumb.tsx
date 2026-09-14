import { useLayoutEffect, useState, type RefObject } from "react";
import { Liquid } from "liquid-gooey";

import { LIQUID_ITEM_RADIUS, LIQUID_MOVE } from "@ageval/shared/lib/liquid";
import { cn } from "@ageval/shared/lib/utils";

export type LiquidBar = { x: number; y: number; w: number; h: number };

export function useTrackedRect(
  rootRef: RefObject<HTMLElement | null>,
  selector: string,
  identity: string,
): { bar: LiquidBar; ready: boolean } {
  const [bar, setBar] = useState<LiquidBar>({ x: 0, y: 0, w: 0, h: 0 });
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const target = root.querySelector<HTMLElement>(selector);
    if (!target) {
      setBar({ x: 0, y: 0, w: 0, h: 0 });
      setReady(false);
      return;
    }

    const measure = () => {
      const r = root.getBoundingClientRect();
      const t = target.getBoundingClientRect();
      setBar({
        x: t.left - r.left + root.scrollLeft,
        y: t.top - r.top + root.scrollTop,
        w: t.width,
        h: t.height,
      });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    ro.observe(target);
    return () => ro.disconnect();
  }, [rootRef, selector, identity]);

  useLayoutEffect(() => {
    if (bar.w === 0 || ready) return;
    const frame = window.requestAnimationFrame(() => setReady(true));
    return () => window.cancelAnimationFrame(frame);
  }, [bar.w, ready]);

  return { bar, ready };
}

/** Move-effect thumb. Must render inside `<Liquid>`. Background stays transparent. */
export function LiquidThumb({
  bar,
  ready,
  className,
}: {
  bar: LiquidBar;
  ready: boolean;
  className?: string;
}) {
  if (bar.w <= 0 || bar.h <= 0) return null;
  return (
    <Liquid.Item
      effect="move"
      observe
      move={LIQUID_MOVE}
      radius={LIQUID_ITEM_RADIUS}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-0 left-0 rounded-[8px]",
          ready &&
            "motion-safe:transition-[transform,width,height] motion-safe:duration-200 motion-safe:ease-glide",
          className,
        )}
        style={{
          width: bar.w,
          height: bar.h,
          borderRadius: LIQUID_ITEM_RADIUS,
          transform: `translate(${bar.x}px, ${bar.y}px)`,
        }}
      />
    </Liquid.Item>
  );
}
