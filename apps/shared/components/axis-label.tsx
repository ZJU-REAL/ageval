import { HoverTip, TruncateTip } from "@ageval/shared/components/hover-tip";
import { formatAxisLabel } from "@ageval/shared/lib/utils";

export function AxisLabel({
  value,
  className,
  empty = "-",
}: {
  value?: string | null;
  className?: string;
  empty?: string;
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
  return <TruncateTip text={value} className={className} />;
}
