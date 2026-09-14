import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { LabMark } from "@ageval/shared/components/lab-mark";
import { ModalityMarks } from "@/components/modality-mark";
import {
  compactTokens,
  directoryPrice,
  fmtPrice,
  loadModelPin,
  modalityBadges,
  modelModalities,
} from "@ageval/shared/lib/model-pin";
import { cn } from "@ageval/shared/lib/utils";

const META_CHIP =
  "whitespace-nowrap rounded-[6px] border border-hairline px-1.5 py-0.5 text-xs leading-4 text-mute tabular-nums";

export function ModelItem({
  canonical,
  overlay = "",
  selected = false,
  extra,
  meta = "full",
  href,
  replace,
  className,
  title,
  onClick,
  onMouseEnter,
  role,
  ...rest
}: {
  canonical?: string | null;
  overlay?: string;
  selected?: boolean;
  extra?: ReactNode;
  /** full = context / price / released; compact = context / price (harness list). */
  meta?: "full" | "compact";
  href?: string;
  replace?: boolean;
  className?: string;
  title?: string;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  onMouseEnter?: (event: MouseEvent<HTMLElement>) => void;
  role?: string;
  "aria-selected"?: boolean;
  "data-index"?: number;
}) {
  const pin = loadModelPin();
  const info = canonical ? pin.models[canonical] : undefined;
  const name = info?.name || overlay || canonical || "";
  const subtitle = canonical || overlay;
  const badges = info ? modalityBadges(modelModalities(info)) : [];
  const price = directoryPrice(canonical, overlay || canonical || "", pin);
  const lab = info?.lab || overlay || canonical || "";

  const inner = (
    <>
      <LabMark lab={lab} size={28} />
      <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
        <span className="flex min-w-0 flex-nowrap items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{name}</span>
          {badges.length ? <ModalityMarks kinds={badges} /> : null}
          {extra}
        </span>
        {subtitle ? (
          <span className="w-full truncate text-xs text-mute">{subtitle}</span>
        ) : null}
      </span>
      <span
        className={cn(
          "ml-auto shrink-0 items-center gap-1.5",
          meta === "compact" ? "flex" : "hidden @[36rem]:flex",
        )}
      >
        {info?.context != null ? (
          <span
            className={META_CHIP}
            title={`${info.context.toLocaleString()} tok`}
          >
            {compactTokens(info.context)} context
          </span>
        ) : null}
        {price ? (
          <span className={META_CHIP}>
            ${fmtPrice(price.input)} / ${fmtPrice(price.output)}
          </span>
        ) : null}
        {meta === "full" && info?.release_date ? (
          <span className={META_CHIP}>{info.release_date}</span>
        ) : null}
      </span>
    </>
  );

  const cls = cn(
    "@container flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left transition-colors duration-200 ease-smooth",
    selected ? "bg-canvas-soft-2" : "hover:bg-canvas-soft",
    className,
  );

  if (href) {
    return (
      <Link
        to={href}
        replace={replace}
        title={title}
        role={role}
        aria-current={selected ? "page" : undefined}
        onClick={onClick}
        onMouseEnter={onMouseEnter}
        className={cls}
        {...rest}
      >
        {inner}
      </Link>
    );
  }

  return (
    <button
      type="button"
      title={title}
      role={role}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={cls}
      {...rest}
    >
      {inner}
    </button>
  );
}
