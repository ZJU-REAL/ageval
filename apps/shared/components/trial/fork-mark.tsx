import { metaChipClass } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

export type ForkMarkData = {
  parent_attempt_id?: string | null;
  checkpoint_seq?: number | null;
  source_model?: string | null;
  continuation_model?: string | null;
};

export function ForkMark({
  fork,
  className,
}: {
  fork?: ForkMarkData | null;
  className?: string;
}) {
  if (!fork?.parent_attempt_id) return null;
  const source = fork.source_model?.trim() || "";
  const continuation = fork.continuation_model?.trim() || "";
  const models =
    source && continuation ? `${source} → ${continuation}` : continuation || source;
  const seq =
    typeof fork.checkpoint_seq === "number" ? `seq ${fork.checkpoint_seq}` : "";
  const label = ["fork", models, seq].filter(Boolean).join(" · ");
  return (
    <span className={cn(metaChipClass, className)} title={fork.parent_attempt_id}>
      {label}
    </span>
  );
}
