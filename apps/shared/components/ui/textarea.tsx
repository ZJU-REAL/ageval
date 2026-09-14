import * as React from "react";

import { cn } from "@ageval/shared/lib/utils";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        "min-h-[5.5rem] w-full resize-y rounded-[10px] border border-hairline bg-canvas px-3.5 py-2.5 text-sm text-ink placeholder:text-mute shadow-none transition-colors duration-200 ease-smooth focus-visible:outline-none focus-visible:border-link disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";
