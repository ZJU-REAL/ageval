import { Slot } from "@radix-ui/react-slot";
import * as React from "react";

import { cn } from "@/lib/utils";

/** Fill-in slot: hairline dashed underline. Optional hover menu for a quick pick. */
export const dashButtonClass = cn(
  "inline-flex h-auto min-h-0 min-w-0 max-w-[16rem] items-center gap-1.5 align-middle",
  "rounded-none border-0 border-b border-dashed border-hairline bg-transparent px-0.5 pb-px",
  "text-sm font-medium text-ink",
  "motion-safe:transition-[border-color,color] motion-safe:duration-200 motion-safe:ease-smooth",
  "hover:border-mute group-hover/dash:border-mute",
  "focus-visible:outline-none focus-visible:border-mute",
  "disabled:pointer-events-none disabled:opacity-50",
);

export function DashMenuItem({
  selected = false,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean }) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      className={cn(
        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm text-ink",
        "motion-safe:transition-colors motion-safe:duration-200 motion-safe:ease-smooth",
        selected ? "bg-canvas-soft-2" : "hover:bg-canvas-soft",
        className,
      )}
      {...props}
    />
  );
}

export function DashButton({
  asChild = false,
  empty = false,
  menu,
  className,
  type,
  children,
  disabled,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  asChild?: boolean;
  empty?: boolean;
  menu?: React.ReactNode;
}) {
  const Comp = asChild ? Slot : "button";
  const button = (
    <Comp
      type={asChild ? type : (type ?? "button")}
      disabled={disabled}
      className={cn(dashButtonClass, empty && "text-mute", className)}
      {...props}
    >
      {children}
    </Comp>
  );

  if (!menu) return button;

  return (
    <span
      className={cn(
        "group/dash relative inline-flex max-w-[16rem] align-middle",
        disabled && "pointer-events-none",
      )}
    >
      {button}
      <span
        className={cn(
          "absolute left-0 top-full z-50 min-w-[14rem] max-w-[20rem] pt-1",
          "grid grid-rows-[0fr] opacity-0 pointer-events-none",
          "motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-200 motion-safe:ease-smooth",
          "group-hover/dash:grid-rows-[1fr] group-hover/dash:opacity-100 group-hover/dash:pointer-events-auto",
          "motion-reduce:transition-none",
        )}
      >
        <span className="min-h-0 overflow-hidden">
          <span
            role="listbox"
            className="block max-h-56 overflow-y-auto rounded-[8px] border border-hairline bg-canvas py-1 shadow-[var(--viewer-shadow-pop)]"
          >
            {menu}
          </span>
        </span>
      </span>
    </span>
  );
}
