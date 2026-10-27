import { GitBranch, MapPin } from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import { metaChipClass } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

export type ReplayMarkData = {
  parent_attempt_id?: string | null;
  status?: string | null;
  field?: string | null;
  ordinal?: number | null;
  artifact_id?: string | null;
  first_divergence?: {
    field?: string | null;
    ordinal?: number | null;
    artifact_id?: string | null;
  } | null;
};

function divergenceLabel(replay: ReplayMarkData): string {
  const point = replay.first_divergence;
  const field = (replay.field || point?.field || "").trim();
  const ordinal = replay.ordinal ?? point?.ordinal;
  const artifact = (replay.artifact_id || point?.artifact_id || "").trim();
  if (!field) return "none";
  const where = ordinal != null ? `${field} at ${ordinal}` : field;
  return artifact ? `${where} (${artifact})` : where;
}

export function ReplayMark({
  replay,
  className,
}: {
  replay?: ReplayMarkData | null;
  className?: string;
}) {
  if (!replay) return null;
  const parent = replay.parent_attempt_id?.trim();
  if (!parent) return null;
  const status = replay.status?.trim() || "replay";
  return (
    <HoverTip
      content={
        <div className="space-y-2">
          <div className="flex items-start gap-2">
            <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" aria-hidden />
            <div className="min-w-0">
              <div className="text-[11px] leading-4 text-mute">Source attempt</div>
              <div className="font-mono text-sm leading-5 text-ink break-all">{parent}</div>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" aria-hidden />
            <div className="min-w-0">
              <div className="text-[11px] leading-4 text-mute">Divergence</div>
              <div className="text-sm leading-5 text-ink">{divergenceLabel(replay)}</div>
            </div>
          </div>
        </div>
      }
    >
      <span className={cn(metaChipClass, "shrink-0 cursor-help", className)}>
        {status === "diverged" ? "replay diverged" : "replay"}
      </span>
    </HoverTip>
  );
}
