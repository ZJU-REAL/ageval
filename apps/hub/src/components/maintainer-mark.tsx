import { ShieldUser } from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";

const TIP = "Platform maintainer";

export function MaintainerMark({ className = "" }: { className?: string }) {
  return (
    <HoverTip content={TIP}>
      <span
        className={`inline-flex shrink-0 text-nav-home ${className}`.trim()}
        aria-label={TIP}
        onClick={(event) => event.stopPropagation()}
      >
        <ShieldUser className="size-4" strokeWidth={2} aria-hidden />
      </span>
    </HoverTip>
  );
}
