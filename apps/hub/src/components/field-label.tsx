import type { ReactNode } from "react";
import { Info } from "lucide-react";

import { HoverTip } from "@/components/hover-tip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Section / field title: ink, sentence case. Optional info tooltip. */
export function FieldLabel({
  children,
  htmlFor,
  className,
  hint,
}: {
  children: ReactNode;
  htmlFor?: string;
  className?: string;
  hint?: ReactNode;
}) {
  const cls = cn("text-sm font-medium text-ink", className);
  const title = htmlFor ? (
    <label htmlFor={htmlFor} className={cls}>
      {children}
    </label>
  ) : hint ? (
    <span className={cls}>{children}</span>
  ) : (
    <p className={cls}>{children}</p>
  );
  if (!hint) return title;
  const about =
    typeof children === "string" ? `About ${children}` : "About this section";
  return (
    <div className="flex items-center gap-1">
      {title}
      <HoverTip content={hint}>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={about}
          className="h-5 w-5 text-mute hover:text-ink"
        >
          <Info className="size-3.5" aria-hidden />
        </Button>
      </HoverTip>
    </div>
  );
}
