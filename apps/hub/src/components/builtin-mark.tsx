import { HousePlug } from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";

const TIP = "Builtin plugin";

export function BuiltinMark({ className = "" }: { className?: string }) {
  return (
    <HoverTip content={TIP}>
      <span
        className={`inline-flex shrink-0 text-link ${className}`.trim()}
        aria-label={TIP}
        onClick={(event) => event.stopPropagation()}
      >
        <HousePlug className="size-4" strokeWidth={2} aria-hidden />
      </span>
    </HoverTip>
  );
}
