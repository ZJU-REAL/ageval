import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as React from "react";

import { useOverlayRoot } from "@ageval/shared/components/overlay-root";
import { cn } from "@ageval/shared/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, onClick, ...props }, ref) => {
  const container = useOverlayRoot();
  return (
  <TooltipPrimitive.Portal container={container}>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      data-ageval-pop=""
      className={cn(
        "pointer-events-auto z-[70] max-w-xs select-text rounded-[10px] border border-hairline bg-canvas px-2.5 py-1.5 text-xs text-ink shadow-[var(--viewer-shadow-pop)]",
        className,
      )}
      {...props}
      onClick={(event) => {
        onClick?.(event);
        // createPortal delivers this click to the row that rendered the pop.
        event.stopPropagation();
      }}
    />
  </TooltipPrimitive.Portal>
  );
});
TooltipContent.displayName = TooltipPrimitive.Content.displayName;
