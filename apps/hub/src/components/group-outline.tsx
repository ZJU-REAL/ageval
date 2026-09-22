import { useState, type ReactNode } from "react";

import { cn } from "@ageval/shared/lib/utils";

export type GroupOutlineItem = {
  id: string;
  name: string;
  count: number;
  mark?: ReactNode;
};

export function groupSectionId(prefix: string) {
  return (id: string) => `${prefix}-${id}`;
}

const BAR_MIN = 10;
const BAR_MAX = 24;

function barWidth(count: number, minCount: number, maxCount: number) {
  if (maxCount <= minCount) return (BAR_MIN + BAR_MAX) / 2;
  const t = Math.sqrt((count - minCount) / (maxCount - minCount));
  return BAR_MIN + t * (BAR_MAX - BAR_MIN);
}

export function GroupOutline({
  items,
  activeId,
  label,
  chromeId,
  sectionId,
  stickVar,
}: {
  items: GroupOutlineItem[];
  activeId: string | null;
  label: string;
  chromeId: string;
  sectionId: (id: string) => string;
  /** Custom property name, including dashes. Example: `--models-stick-top`. */
  stickVar: string;
}) {
  const [pointerOpen, setPointerOpen] = useState(false);
  const [kbdOpen, setKbdOpen] = useState(false);
  const open = pointerOpen || kbdOpen;

  if (items.length < 2) return null;

  const counts = items.map((item) => item.count);
  const minCount = Math.min(...counts);
  const maxCount = Math.max(...counts);

  function go(id: string) {
    const main = document.getElementById("main");
    const chrome = document.getElementById(chromeId);
    const el = document.getElementById(sectionId(id));
    if (!main || !el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const align = () => {
      const line =
        chrome?.getBoundingClientRect().bottom ?? main.getBoundingClientRect().top;
      const table = el.querySelector(".blob-panel");
      const target = table instanceof HTMLElement ? table : el;
      return Math.max(0, target.getBoundingClientRect().top - line + main.scrollTop);
    };
    const top = align();
    const smooth = !reduced && Math.abs(top - main.scrollTop) < 1600;
    let follow = !smooth;
    const correct = () => {
      if (!follow) return;
      const next = align();
      if (Math.abs(next - main.scrollTop) > 1) {
        main.scrollTo({ top: next, behavior: "auto" });
      }
    };
    main.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
    // Opening the pin slot grows the sticky chrome after the jump is aimed.
    if (chrome) {
      const ro = new ResizeObserver(() => correct());
      ro.observe(chrome);
      window.setTimeout(() => ro.disconnect(), 700);
    }
    if (smooth) {
      main.addEventListener(
        "scrollend",
        () => {
          follow = true;
          correct();
          requestAnimationFrame(correct);
        },
        { once: true },
      );
    } else {
      requestAnimationFrame(() => requestAnimationFrame(correct));
    }
  }

  return (
    <nav
      aria-label={label}
      onPointerEnter={() => setPointerOpen(true)}
      onPointerLeave={() => setPointerOpen(false)}
      onFocus={() => setKbdOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setKbdOpen(false);
        }
      }}
      style={{
        maxHeight: `calc(100dvh - 4.5rem - var(${stickVar}, 0px) - 2.25rem)`,
      }}
      className={cn(
        "w-max shrink-0 overflow-y-auto overscroll-contain rounded-[10px] p-1",
        "motion-safe:transition-[background-color,box-shadow] motion-safe:duration-200 motion-safe:ease-smooth",
        open && "bg-canvas shadow-[var(--viewer-shadow-pop)]",
        "motion-reduce:transition-none",
      )}
    >
      <ul className="flex flex-col">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li key={item.id}>
              <button
                type="button"
                aria-label={`${item.name}, ${item.count}`}
                aria-current={active ? "location" : undefined}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => go(item.id)}
                className={cn(
                  "flex w-full items-center justify-end gap-2 overflow-hidden rounded-[8px] px-1",
                  open ? "h-7" : "h-3",
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
                    open ? "w-[11rem] opacity-100" : "w-0 opacity-0",
                    "motion-reduce:transition-none",
                  )}
                >
                  <span className="flex w-[11rem] items-center gap-1.5">
                    {item.mark ? (
                      <span className="shrink-0">{item.mark}</span>
                    ) : null}
                    <span
                      className={cn(
                        "min-w-0 truncate text-sm",
                        active ? "font-medium text-ink" : "text-body",
                      )}
                    >
                      {item.name}
                    </span>
                  </span>
                </span>
                {open ? (
                  <span className="min-w-[1.25rem] text-right text-xs tabular-nums text-mute">
                    {item.count}
                  </span>
                ) : (
                  <span
                    className={cn(
                      "h-0.5 shrink-0 rounded-full",
                      active ? "bg-ink" : "bg-hairline-strong",
                    )}
                    style={{
                      width: barWidth(item.count, minCount, maxCount),
                    }}
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

/** Right-edge rail. `lg` reserves a hairline column; `xl` sits in the 80% gutter. */
export function GroupOutlineRail({
  items,
  activeId,
  label,
  chromeId,
  sectionId,
  stickVar,
  children,
}: {
  items: GroupOutlineItem[];
  activeId: string | null;
  label: string;
  chromeId: string;
  sectionId: (id: string) => string;
  stickVar: string;
  children: ReactNode;
}) {
  if (items.length < 2) return children;

  return (
    <div className="relative lg:pr-10 xl:pr-0">
      {children}
      <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-10 lg:block xl:left-full xl:right-auto xl:w-[12.5%] xl:pl-3">
        <div
          className="pointer-events-auto sticky z-10 flex w-full justify-end overflow-visible"
          style={{ top: `calc(var(${stickVar}, 0px) + 0.75rem)` }}
        >
          <GroupOutline
            items={items}
            activeId={activeId}
            label={label}
            chromeId={chromeId}
            sectionId={sectionId}
            stickVar={stickVar}
          />
        </div>
      </div>
    </div>
  );
}
