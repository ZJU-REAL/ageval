import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        "flex h-9 w-full rounded-full border border-hairline bg-canvas px-3.5 py-1 text-sm text-ink placeholder:text-mute shadow-none transition-colors duration-200 ease-smooth focus-visible:outline-none focus-visible:border-hairline disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Input.displayName = "Input";
