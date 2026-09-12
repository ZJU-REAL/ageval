import type { ReactNode } from "react";

import { HoverTip } from "@/components/hover-tip";
import {
  SlotHistorySelect,
  type SlotHistoryEntry,
} from "@/components/trial/slot-history-select";
import { EXTERNAL_LINK_CLASS } from "@/lib/links";
import type { Trial } from "@/lib/trial-types";

/** Header without sibling nav (Hub has no local trial list siblings by default). */
export function TrialHeader({
  runId,
  taskId,
  trial,
  slotCurrentRunId,
  slotCurrentStartedAt,
  slotPrevious,
  onSlotSelect,
  actions,
}: {
  runId: string;
  taskId: string;
  trial: Trial | null;
  slotCurrentRunId?: string | null;
  slotCurrentStartedAt?: string | null;
  slotPrevious?: SlotHistoryEntry[];
  onSlotSelect?: (id: string) => void;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-2xl font-semibold tracking-tight text-ink font-mono truncate">
          {runId}
        </h1>
        <p className="text-xs text-mute mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <span>
            task <span className="text-body font-medium">{taskId}</span>
          </span>
          {trial?.dataset_ref ? (
            <>
              <span className="text-mute select-none" aria-hidden>
                ·
              </span>
              <span className="text-body font-medium">
                {trial.dataset_ref}
              </span>
            </>
          ) : null}
          {trial?.framework ? (
            <>
              <span className="text-mute select-none" aria-hidden>
                ·
              </span>
              <span className="text-body font-medium">
                {trial.framework}
              </span>
            </>
          ) : null}
          {trial?.environment ? (
            <>
              <span className="text-mute select-none" aria-hidden>
                ·
              </span>
              <span className="text-body font-medium">
                {trial.environment}
              </span>
            </>
          ) : null}
          {trial?.upstream_url ? (
            <>
              <span className="text-mute select-none" aria-hidden>
                ·
              </span>
              <HoverTip content={trial.upstream_name || trial.upstream_url}>
                <a
                  href={trial.upstream_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`${EXTERNAL_LINK_CLASS} truncate max-w-[min(48ch,100%)]`}
                >
                  {trial.upstream_url}
                </a>
              </HoverTip>
            </>
          ) : null}
        </p>
      </div>
      {actions || onSlotSelect ? (
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          {onSlotSelect ? (
            <SlotHistorySelect
              viewingRunId={runId}
              currentRunId={slotCurrentRunId}
              previous={slotPrevious}
              currentAt={slotCurrentStartedAt ?? trial?.started}
              onSelect={onSlotSelect}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
