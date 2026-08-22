import { Box } from "lucide-react";

import { HoverTip } from "@/components/hover-tip";

const TIP = "Ships with ageval";

export function BuiltinMark({ className = "" }: { className?: string }) {
  return (
    <HoverTip content={TIP}>
      <span
        className={`inline-flex shrink-0 text-mute ${className}`.trim()}
        aria-label={TIP}
        onClick={(event) => event.stopPropagation()}
      >
        <Box className="size-4" strokeWidth={2} aria-hidden />
      </span>
    </HoverTip>
  );
}
