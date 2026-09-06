import { BrandMark } from "@/components/brand-mark";
import { BuiltinMark } from "@/components/builtin-mark";
import { OfficialMark } from "@/components/official-mark";
import { markFromPackage } from "@/lib/brand-marks";
import {
  isBuiltinPackage,
  packageDisplayTitle,
  type PackageRelease,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** One harness / agent row in the attach search palette (ModelItem layout). */
export function AgentItem({
  row,
  selected = false,
  onClick,
  onMouseEnter,
  index,
}: {
  row: PackageRelease;
  selected?: boolean;
  onClick?: () => void;
  onMouseEnter?: () => void;
  index?: number;
}) {
  const builtin = isBuiltinPackage(row);
  const title = packageDisplayTitle(row.dataset_id, row.display_name);
  const subtitle = row.dataset_id;
  const meta = builtin ? "bundled" : row.version ? `v${row.version}` : "";

  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-index={index}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={cn(
        "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left transition-colors duration-200 ease-smooth",
        selected ? "bg-canvas-soft-2" : "hover:bg-canvas-soft",
      )}
    >
      <BrandMark mark={markFromPackage(row)} size={28} />
      <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
        <span className="flex min-w-0 flex-nowrap items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{title}</span>
          {builtin ? <BuiltinMark /> : row.official ? <OfficialMark /> : null}
        </span>
        {subtitle ? (
          <span className="w-full truncate text-xs text-mute">{subtitle}</span>
        ) : null}
      </span>
      {meta ? (
        <span className="ml-auto shrink-0 whitespace-nowrap rounded-[6px] border border-hairline px-1.5 py-0.5 text-xs leading-4 text-mute">
          {meta}
        </span>
      ) : null}
    </button>
  );
}
