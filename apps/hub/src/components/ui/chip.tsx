import { Slot } from "@radix-ui/react-slot";
import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

export function Chip({
  selected = false,
  asChild = false,
  size = "md",
  className,
  ...props
}: React.ComponentPropsWithoutRef<"span"> & {
  selected?: boolean;
  asChild?: boolean;
  size?: "md" | "sm";
}) {
  const Comp = asChild ? Slot : "span";
  return (
    <Comp
      className={cn(
        "inline-flex max-w-full items-center truncate rounded-[8px] border border-hairline",
        "transition-colors duration-200 ease-smooth",
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2.5 py-1 text-sm",
        selected
          ? "bg-canvas-soft-2 text-ink"
          : "bg-canvas text-body hover:bg-canvas-soft hover:text-ink",
        className,
      )}
      {...props}
    />
  );
}
