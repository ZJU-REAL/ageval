import type { MouseEvent } from "react";
import { Link } from "react-router-dom";

import { HoverTip, TruncateTip } from "@ageval/shared/components/hover-tip";
import { LabMark } from "@ageval/shared/components/lab-mark";
import { INTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";
import { loadModelPin, overlayLab } from "@ageval/shared/lib/model-pin";
import { cn, formatModelLabel } from "@ageval/shared/lib/utils";

export function ModelLabel({
  value,
  effort,
  className,
  empty = "-",
  to,
  onClick,
  mark = true,
  clip = true,
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
  /** False keeps the full label so a wide table can scroll instead of ellipsizing. */
  clip?: boolean;
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
            clip
              ? "inline-block w-max min-w-0 max-w-full truncate"
              : "whitespace-nowrap",
            !to && "cursor-help",
          )}
        >
          {shown}
        </span>
      </HoverTip>
    ) : (
      <TruncateTip text={shown} clip={clip} />
    );

  return (
    <span
      className={cn(
        "inline-flex items-center",
        clip && "min-w-0 max-w-full",
        className,
      )}
    >
      {lab ? <LabMark lab={lab} size={16} className="mr-1.5" /> : null}
      {to ? (
        <Link
          to={to}
          onClick={(event) => {
            event.stopPropagation();
            onClick?.(event);
          }}
          className={cn(clip && "min-w-0", "inline-flex", INTERNAL_LINK_CLASS)}
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
