import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

/**
 * Quiet hover shared with UnderlineTabs.
 * Fade comes from `squish` (200ms). Do not restate these utilities at a call site.
 */
export const quietHoverClass =
  "text-mute hover:bg-liquid-hover hover:text-ink";

/**
 * Aside and the Viewer header sit on canvas-soft.
 * `liquid-hover` is that same surface, so it would not show.
 */
export const sidebarHoverClass = "hover:bg-canvas/50 hover:text-ink";

/** One hairline group. Inner radius stays 8. Do not use 6px. */
export const segmentGroupClass =
  "inline-flex shrink-0 items-center gap-0.5 rounded-[8px] border border-hairline bg-canvas p-0.5";

export const segmentItemClass =
  "rounded-[8px] px-2.5 py-1 text-sm transition-colors duration-200 ease-smooth focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

export const segmentOnClass = "bg-canvas-soft-2 text-ink";

export const segmentOffClass = "text-body hover:bg-canvas-soft";

/**
 * File-tree row. Not a Button. Selected fill is canvas-soft-2.
 * Hub and the trial tree share this; do not use 4px or row-hover.
 */
export const treeRowClass =
  "flex w-full items-center text-left h-7 pr-2 text-sm rounded-[8px] transition-colors duration-200 ease-smooth focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

export const treeRowIdleClass = "text-body hover:bg-canvas-soft";

export const treeRowOnClass = "bg-canvas-soft-2 font-medium text-ink";

/** Static meta label (context, price, builtin). Radius 8. Not a control. */
export const metaChipClass =
  "inline-flex max-w-full items-center truncate whitespace-nowrap rounded-[8px] border border-hairline bg-canvas px-1.5 py-0.5 text-xs leading-4 text-mute";

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
        /** On a text line (trajectory step head). 20px box, 4px radius so it stays a button. */
        iconSm: "h-5 w-5 rounded-[4px]",
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

/** Single-choice or multi-choice items inside one hairline box. */
export function SegmentedControl<T extends string>({
  label,
  items,
  selected,
  onSelect,
  className,
  itemClassName,
}: {
  label: string;
  items: readonly { id: T; label: string }[];
  selected: (id: T) => boolean;
  onSelect: (id: T) => void;
  className?: string;
  itemClassName?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(segmentGroupClass, className)}
    >
      {items.map((item) => {
        const on = selected(item.id);
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={on}
            onClick={() => onSelect(item.id)}
            className={cn(
              segmentItemClass,
              on ? segmentOnClass : segmentOffClass,
              itemClassName,
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
