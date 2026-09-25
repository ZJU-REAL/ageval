import type { MouseEvent } from "react";
import { Link } from "react-router-dom";

import { BrandMark } from "@ageval/shared/components/brand-mark";
import { HoverTip, TruncateTip } from "@ageval/shared/components/hover-tip";
import {
  BRAND_MARK_BY_ID,
  markFromPackage,
  type PackageMarkSource,
  type ResolvedMark,
} from "@ageval/shared/lib/brand-marks";
import { harnessBrandId } from "@ageval/shared/lib/brand-marks/harness";
import { INTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";
import { cn, formatAxisLabel } from "@ageval/shared/lib/utils";

function resolvedHarnessMark(
  value: string,
  pack?: PackageMarkSource | null,
): ResolvedMark | null {
  const id = harnessBrandId(value);
  if (id) return { kind: "catalog", id };
  if (!pack) return null;
  const mark = markFromPackage(pack);
  if (mark.kind === "letter") return null;
  return mark;
}

export function HarnessLabel({
  value,
  className,
  empty = "-",
  to,
  onClick,
  mark = true,
  pack,
  clip = true,
}: {
  value?: string | null;
  className?: string;
  empty?: string;
  to?: string;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /**
   * Prepend BrandMark when the id uniquely maps to a builtin catalog mark,
   * or when ``pack`` has a catalog / GitHub icon. Off only if a parent already
   * shows the same harness identity.
   */
  mark?: boolean;
  pack?: PackageMarkSource | null;
  /** False keeps the full label so a wide table can scroll instead of ellipsizing. */
  clip?: boolean;
}) {
  const { text, title } = formatAxisLabel(value);
  const extraTitle = title && title !== text ? title : "";
  const shown = text === "-" ? empty : text;
  if (!value?.trim() || shown === empty) {
    return <span className={className}>{shown}</span>;
  }

  const resolved = mark ? resolvedHarnessMark(value, pack) : null;

  const name =
    extraTitle ? (
      <HoverTip content={extraTitle}>
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
      {resolved ? (
        <BrandMark
          mark={resolved}
          size={16}
          className="mr-1.5"
          title={
            resolved.kind === "catalog"
              ? BRAND_MARK_BY_ID.get(resolved.id)?.label
              : resolved.kind === "github"
                ? resolved.login
                : undefined
          }
        />
      ) : null}
      {to ? (
        <Link
          to={to}
          onClick={(event) => {
            event.stopPropagation();
            onClick?.(event);
          }}
          className={cn(clip && "min-w-0", "inline-flex", INTERNAL_LINK_CLASS)}
        >
          {name}
        </Link>
      ) : (
        name
      )}
    </span>
  );
}
