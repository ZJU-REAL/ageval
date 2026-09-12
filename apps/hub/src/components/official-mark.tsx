import { BadgeCheck } from "lucide-react";

import { HoverTip } from "@/components/hover-tip";

const TIPS = {
  plugin: "Verified official plugin",
  org: "Verified official organization",
  dataset: "Verified official dataset",
} as const;

export function OfficialMark({
  className = "",
  kind = "plugin",
}: {
  className?: string;
  kind?: keyof typeof TIPS;
}) {
  const tip = TIPS[kind];
  return (
    <HoverTip content={tip}>
      <span
        className={`inline-flex shrink-0 text-link ${className}`.trim()}
        aria-label={tip}
        onClick={(event) => event.stopPropagation()}
      >
        <BadgeCheck className="size-4" strokeWidth={2} aria-hidden />
      </span>
    </HoverTip>
  );
}
