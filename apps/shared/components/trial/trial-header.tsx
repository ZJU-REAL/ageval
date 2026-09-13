import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import {
  SlotHistorySelect,
  type SlotHistoryEntry,
} from "@ageval/shared/components/trial/slot-history-select";
import { Button } from "@ageval/shared/components/ui/button";
import { EXTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";
import type { Trial } from "@ageval/shared/lib/trial-types";

/** Header without required sibling nav (Hub has none by default). */
export function TrialHeader({
  runId,
  taskId,
  trial,
  prevId,
  nextId,
  onSibling,
  slotCurrentRunId,
  slotCurrentStartedAt,
  slotPrevious,
  onSlotSelect,
  actions,
  documentTitle = false,
}: {
  runId: string;
  taskId: string;
  trial: Trial | null;
  prevId?: string | null;
  nextId?: string | null;
  onSibling?: (id: string | null) => void;
  slotCurrentRunId?: string | null;
  slotCurrentStartedAt?: string | null;
  slotPrevious?: SlotHistoryEntry[];
  onSlotSelect?: (id: string) => void;
  actions?: ReactNode;
  documentTitle?: boolean;
}) {
  useEffect(() => {
    if (!documentTitle) return;
    const previous = document.title;
    document.title = `${runId} · ageval`;
    return () => {
      document.title = previous;
    };
  }, [documentTitle, runId]);

  const siblingNav = onSibling ? (
    <>
      <Button
        type="button"
        variant="outline"
        size="icon"
        disabled={!prevId}
        onClick={() => onSibling(prevId ?? null)}
        aria-label="Previous trial"
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        disabled={!nextId}
        onClick={() => onSibling(nextId ?? null)}
        aria-label="Next trial"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </>
  ) : null;

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
      {actions || onSlotSelect || siblingNav ? (
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
          {siblingNav}
        </div>
      ) : null}
    </div>
  );
}
