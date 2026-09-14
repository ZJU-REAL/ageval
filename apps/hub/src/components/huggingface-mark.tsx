import { cn } from "@ageval/shared/lib/utils";

/** Vendored Lobe static color SVG. Not a runtime @lobehub/icons import. */
export function HuggingFaceMark({
  size = 16,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <img
      src="/model-pin/huggingface.svg"
      alt=""
      width={size}
      height={size}
      className={cn("inline-block shrink-0", className)}
      aria-hidden
    />
  );
}
