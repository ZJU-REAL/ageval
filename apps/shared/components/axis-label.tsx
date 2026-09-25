import { HoverTip, TruncateTip } from "@ageval/shared/components/hover-tip";
import { formatAxisLabel } from "@ageval/shared/lib/utils";

export function AxisLabel({
  value,
  className,
  empty = "-",
  clip = true,
}: {
  value?: string | null;
  className?: string;
  empty?: string;
  /** False keeps the full label so a wide table can scroll instead of ellipsizing. */
  clip?: boolean;
}) {
  const { text, title } = formatAxisLabel(value);
  const shown = text === "-" ? empty : text;
  const compacted = Boolean(title && title.includes("+") && text.endsWith("+..."));
  if (compacted) {
    return (
      <HoverTip content={title}>
        <span className={`${className ?? ""} cursor-help`.trim()}>{shown}</span>
      </HoverTip>
    );
  }
  if (!value?.trim() || shown === empty) {
    return <span className={className}>{shown}</span>;
  }
  return <TruncateTip text={value} className={className} clip={clip} />;
}
