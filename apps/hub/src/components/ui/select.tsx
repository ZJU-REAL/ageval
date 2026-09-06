import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";

import { useOverlayRoot } from "@/components/overlay-root";
import { cn } from "@/lib/utils";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "group flex h-9 select-none items-center justify-between gap-2 rounded-[8px] border border-hairline bg-canvas px-3.5 text-sm text-ink squish",
      "focus:outline-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/40 disabled:cursor-not-allowed disabled:opacity-50",
      "data-[placeholder]:text-mute min-w-[9rem]",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-3.5 w-3.5 text-mute motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-smooth group-data-[state=open]:rotate-180" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => {
  const container = useOverlayRoot();
  return (
  <SelectPrimitive.Portal container={container}>
    <SelectPrimitive.Content
      ref={ref}
      data-ageval-menu=""
      className={cn(
        "z-[70] min-w-[8rem] overflow-hidden rounded-[12px] border border-hairline bg-canvas text-ink shadow-[var(--viewer-shadow-pop)]",
        "max-h-[min(24rem,var(--radix-select-content-available-height,24rem))]",
        className,
      )}
      position={position}
      {...props}
    >
      <SelectPrimitive.Viewport className="max-h-[inherit] overflow-y-auto overscroll-contain p-1">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
  );
});
SelectContent.displayName = SelectPrimitive.Content.displayName;

export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & {
    trailing?: React.ReactNode;
    /** Version / numeric values stay mono. Human labels (Public / Internal) use sans. */
    mono?: boolean;
  }
>(({ className, children, trailing, mono = true, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-pointer select-none items-center gap-4 rounded-[8px] py-1.5 pl-8 pr-2 text-sm outline-none",
      "transition-colors duration-200 ease-smooth",
      "data-[highlighted]:bg-canvas-soft data-[state=checked]:bg-canvas-soft-2",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-3.5 w-3.5 text-link motion-safe:animate-[ageval-pop_200ms_var(--ease-spring)_both]" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText asChild>
      <span
        className={cn(
          "inline-block shrink-0",
          mono && "min-w-[6ch] font-mono tabular-nums",
        )}
      >
        {children}
      </span>
    </SelectPrimitive.ItemText>
    {trailing != null && trailing !== "" ? (
      <span className="ml-auto shrink-0 text-right text-xs tabular whitespace-nowrap text-mute">
        {trailing}
      </span>
    ) : null}
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;
