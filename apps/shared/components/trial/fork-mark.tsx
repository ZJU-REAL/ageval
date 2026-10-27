import { ArrowRight, GitBranch, Hash, ScrollText, Undo2 } from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import { metaChipClass } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

export type ForkMarkData = {
  parent_attempt_id?: string | null;
  checkpoint_seq?: number | null;
  source_model?: string | null;
  continuation_model?: string | null;
};

function TipRow({
  icon: Icon,
  label,
  value,
  mono = false,
}: {
  icon: typeof GitBranch;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" aria-hidden />
      <div className="min-w-0">
        <div className="text-[11px] leading-4 text-mute">{label}</div>
        <div className={cn("text-sm leading-5 text-ink break-all", mono && "font-mono")}>
          {value}
        </div>
      </div>
    </div>
  );
}

function ForkTip({ fork }: { fork: ForkMarkData }) {
  const source = fork.source_model?.trim() || "—";
  const next = fork.continuation_model?.trim() || "—";
  const seq =
    typeof fork.checkpoint_seq === "number" ? String(fork.checkpoint_seq) : "—";
  const parent = fork.parent_attempt_id?.trim() || "—";
  return (
    <div className="flex w-64 flex-col gap-2">
      <div className="flex items-center gap-2 border-b border-hairline pb-2">
        <GitBranch className="h-3.5 w-3.5 shrink-0 text-mute" aria-hidden />
        <span className="text-sm text-ink">Fork</span>
      </div>
      <TipRow icon={Undo2} label="From" value={source} mono />
      <TipRow icon={ArrowRight} label="To" value={next} mono />
      <TipRow icon={Hash} label="Checkpoint" value={`seq ${seq}`} mono />
      <TipRow icon={ScrollText} label="Parent trajectory" value={parent} mono />
    </div>
  );
}

export function ForkMark({
  fork,
  className,
}: {
  fork?: ForkMarkData | null;
  className?: string;
}) {
  if (!fork?.parent_attempt_id) return null;
  return (
    <HoverTip
      content={<ForkTip fork={fork} />}
      contentClassName="max-w-none break-normal px-3 py-2.5"
    >
      <span className={cn(metaChipClass, "shrink-0 cursor-help", className)}>fork</span>
    </HoverTip>
  );
}

/** Hairline cut in a trajectory: the copied parent steps end here. */
export function ForkCut({ fork }: { fork?: ForkMarkData | null }) {
  if (!fork?.parent_attempt_id) return null;
  const seq =
    typeof fork.checkpoint_seq === "number" ? `seq ${fork.checkpoint_seq}` : "";
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="h-px min-w-4 flex-1 bg-hairline" />
      <ForkMark fork={fork} />
      {seq ? (
        <span className="shrink-0 font-mono text-xs tabular-nums text-mute">{seq}</span>
      ) : null}
      <span className="h-px min-w-4 flex-1 bg-hairline" />
    </div>
  );
}
