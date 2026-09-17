import { LabMark } from "@ageval/shared/components/lab-mark";
import { cn } from "@ageval/shared/lib/utils";

export function modelLabSectionId(id: string) {
  return `model-lab-${id}`;
}

export type ModelLabOutlineItem = {
  id: string;
  lab: string;
  name: string;
};

export function ModelLabOutline({
  items,
  activeId,
}: {
  items: ModelLabOutlineItem[];
  activeId: string | null;
}) {
  if (items.length < 2) return null;

  function go(id: string) {
    const main = document.getElementById("main");
    const chrome = document.getElementById("models-chrome");
    const el = document.getElementById(modelLabSectionId(id));
    if (!main || !el) return;
    const line = chrome?.getBoundingClientRect().bottom ?? main.getBoundingClientRect().top;
    const next =
      el.getBoundingClientRect().top - line + main.scrollTop;
    const top = Math.max(0, next);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const near = Math.abs(top - main.scrollTop) < 1600;
    main.scrollTo({
      top,
      behavior: !reduced && near ? "smooth" : "auto",
    });
  }

  return (
    <nav
      aria-label="Labs"
      className={cn(
        "group/outline max-h-[calc(100dvh-4.5rem-var(--models-stick-top,0px)-2.25rem)]",
        "w-max shrink-0 overflow-y-auto overscroll-contain rounded-[10px] p-1",
        "motion-safe:transition-[background-color,box-shadow] motion-safe:duration-200 motion-safe:ease-smooth",
        "hover:bg-canvas hover:shadow-[var(--viewer-shadow-pop)]",
        "focus-within:bg-canvas focus-within:shadow-[var(--viewer-shadow-pop)]",
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
                aria-label={item.name}
                aria-current={active ? "location" : undefined}
                onClick={(event) => {
                  go(item.id);
                  event.currentTarget.blur();
                }}
                className={cn(
                  "flex w-full items-center justify-end gap-2 rounded-[8px] px-1",
                  "h-3 group-hover/outline:h-7 group-focus-within/outline:h-7",
                  "motion-safe:transition-[height,background-color] motion-safe:duration-200 motion-safe:ease-smooth",
                  "group-hover/outline:hover:bg-canvas-soft",
                  "group-focus-within/outline:hover:bg-canvas-soft",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  "motion-reduce:transition-none",
                )}
              >
                <span
                  className={cn(
                    "grid grid-cols-[0fr] opacity-0",
                    "motion-safe:transition-[grid-template-columns,opacity] motion-safe:duration-200 motion-safe:ease-smooth",
                    "group-hover/outline:grid-cols-[1fr] group-hover/outline:opacity-100",
                    "group-focus-within/outline:grid-cols-[1fr] group-focus-within/outline:opacity-100",
                    "motion-reduce:transition-none",
                  )}
                >
                  <span className="min-w-0 overflow-hidden">
                    <span className="flex w-[11rem] items-center gap-1.5">
                      {item.lab ? (
                        <LabMark lab={item.lab} size={16} className="shrink-0" />
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
                </span>
                <span
                  aria-hidden
                  className={cn(
                    "h-0.5 w-3.5 shrink-0 rounded-full",
                    active ? "bg-ink" : "bg-hairline-strong",
                  )}
                />
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
