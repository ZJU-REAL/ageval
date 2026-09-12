import type { MouseEvent } from "react";
import { Link } from "react-router-dom";

import { HoverTip, TruncateTip } from "@/components/hover-tip";
import { LabMark } from "@/components/lab-mark";
import { INTERNAL_LINK_CLASS } from "@/lib/links";
import { loadModelPin, overlayLab } from "@/lib/model-pin";
import { cn, formatModelLabel } from "@/lib/utils";

export function ModelLabel({
  value,
  effort,
  className,
  empty = "-",
  to,
  onClick,
  mark = true,
}: {
  value?: string | null;
  effort?: string | null;
  className?: string;
  empty?: string;
  /** When set, only the model name is a link; ``[effort]`` stays outside. */
  to?: string;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /**
   * Prepend LabMark when overlay uniquely joins a pin model.
   * Off when the group head already shows the lab (plaza Model / `/models`).
   */
  mark?: boolean;
}) {
  const { text, title } = formatModelLabel(value);
  const extra = (effort || "").trim();
  const shown = text === "-" ? empty : text;
  if (!value?.trim() || shown === empty) {
    return <span className={className}>{shown}</span>;
  }

  const lab = mark ? overlayLab(value, loadModelPin()) : "";

  const model =
    title && title !== shown ? (
      <HoverTip content={title}>
        <span
          className={cn(
            "inline-block w-max min-w-0 max-w-full truncate",
            !to && "cursor-help",
          )}
        >
          {shown}
        </span>
      </HoverTip>
    ) : (
      <TruncateTip text={shown} />
    );

  return (
    <span className={cn("inline-flex min-w-0 max-w-full items-center", className)}>
      {lab ? <LabMark lab={lab} size={16} className="mr-1.5" /> : null}
      {to ? (
        <Link
          to={to}
          onClick={(event) => {
            event.stopPropagation();
            onClick?.(event);
          }}
          className={cn("inline-flex min-w-0", INTERNAL_LINK_CLASS)}
        >
          {model}
        </Link>
      ) : (
        model
      )}
      {extra ? <span className="shrink-0 text-mute">[{extra}]</span> : null}
    </span>
  );
}
