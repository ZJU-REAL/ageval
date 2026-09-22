import { useEffect, useRef, useState, type ComponentType } from "react";

import { cn } from "@ageval/shared/lib/utils";

export type TrajectoryOutlineItem = {
  id: string;
  text: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  tone: string;
  /** Preview length; collapsed bars scale between 10px and 24px. */
  weight: number;
};

const BAR_MIN = 10;
const BAR_MAX = 24;

function barWidth(weight: number, minWeight: number, maxWeight: number) {
  if (maxWeight <= minWeight) return (BAR_MIN + BAR_MAX) / 2;
  const t = Math.sqrt((weight - minWeight) / (maxWeight - minWeight));
  return BAR_MIN + t * (BAR_MAX - BAR_MIN);
}

/** Collapsed hairline rail beside the trajectory port. Hover opens icon + text. */
export function TrajectoryOutline({
  items,
  activeId,
  onJump,
}: {
  items: TrajectoryOutlineItem[];
  activeId: string | null;
  onJump: (id: string) => void;
}) {
  const [pointerOpen, setPointerOpen] = useState(false);
  const [kbdOpen, setKbdOpen] = useState(false);
  const open = pointerOpen || kbdOpen;
  const listRef = useRef<HTMLElement>(null);
  const weights = items.map((item) => item.weight);
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);

  useEffect(() => {
    const list = listRef.current;
    if (!list || !activeId) return;
    const btn = list.querySelector<HTMLElement>(`[data-outline-id="${activeId}"]`);
    if (!btn) return;
    const top = btn.offsetTop;
    const bottom = top + btn.offsetHeight;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (bottom > list.scrollTop + list.clientHeight) {
      list.scrollTop = bottom - list.clientHeight;
    }
  }, [activeId, open]);

  if (items.length < 2) return null;

  return (
    <nav
      ref={listRef}
      aria-label="Trajectory outline"
      onPointerEnter={() => setPointerOpen(true)}
      onPointerLeave={() => setPointerOpen(false)}
      onFocus={() => setKbdOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setKbdOpen(false);
        }
      }}
      className={cn(
        "pointer-events-auto max-h-full w-max shrink-0 overflow-y-auto overscroll-contain rounded-[10px] p-1",
        "motion-safe:transition-[background-color,box-shadow] motion-safe:duration-200 motion-safe:ease-smooth",
        open && "bg-canvas shadow-[var(--viewer-shadow-pop)]",
        "motion-reduce:transition-none",
      )}
    >
      <ul className="flex flex-col">
        {items.map((item) => {
          const active = item.id === activeId;
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <button
                type="button"
                data-outline-id={item.id}
                aria-label={item.text}
                aria-current={active ? "location" : undefined}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => onJump(item.id)}
                className={cn(
                  "flex w-full min-w-0 items-center justify-end overflow-hidden rounded-[8px] px-1",
                  open ? "h-7 gap-2" : "h-3",
                  "motion-safe:transition-[height,background-color] motion-safe:duration-200 motion-safe:ease-smooth",
                  open && active && "bg-canvas-soft",
                  open && "hover:bg-canvas-soft",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  "motion-reduce:transition-none",
                )}
              >
                <span
                  className={cn(
                    "min-w-0 overflow-hidden",
                    "motion-safe:transition-[width,opacity] motion-safe:duration-200 motion-safe:ease-smooth",
                    open ? "w-[13rem] opacity-100" : "w-0 opacity-0",
                    "motion-reduce:transition-none",
                  )}
                >
                  <span className="flex w-[13rem] items-center gap-1.5">
                    <Icon className={cn("size-3.5 shrink-0", item.tone)} aria-hidden />
                    <span
                      className={cn(
                        "min-w-0 truncate text-sm",
                        active ? "font-medium text-ink" : "text-body",
                      )}
                    >
                      {item.text}
                    </span>
                  </span>
                </span>
                {open ? null : (
                  <span
                    className={cn(
                      "h-0.5 shrink-0 rounded-full",
                      active ? "bg-ink" : "bg-hairline-strong",
                    )}
                    style={{ width: barWidth(item.weight, minWeight, maxWeight) }}
                  />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
