import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

/** Quiet hover shared with UnderlineTabs. Fade comes from `squish` (200ms). */
export const quietHoverClass =
  "text-mute hover:bg-liquid-hover hover:text-ink";

const hairlineField =
  "border border-hairline bg-canvas text-ink hover:bg-liquid-hover";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[8px] text-sm font-medium squish focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "border border-cta bg-cta text-on-accent hover:border-cta-deep hover:bg-cta-deep font-mono text-[13px] font-semibold shadow-[var(--viewer-shadow-pop)]",
        secondary: hairlineField,
        ghost: `border border-transparent ${quietHoverClass}`,
        outline: hairlineField,
        danger:
          "border border-error bg-error text-on-accent hover:border-error hover:bg-error/80 font-mono text-[13px] font-semibold shadow-[var(--viewer-shadow-pop)]",
        dangerOutline:
          "border border-hairline bg-canvas text-ink hover:border-transparent hover:bg-error/15 hover:text-error",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 px-3 text-[13px]",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
