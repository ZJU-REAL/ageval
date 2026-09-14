import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { usePeekHistory } from "@/peek-router";

import { OverlayRootProvider } from "@ageval/shared/components/overlay-root";
import { PageHeadSlotProvider } from "@/components/page-head";
import { Button } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

/** Cross-module page host. Close returns to the caller without a route change. */
export function FrameModal({
  open,
  title = "Preview",
  onClose,
  children,
}: {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const [headSlot, setHeadSlot] = useState<HTMLElement | null>(null);
  const [dialogEl, setDialogEl] = useState<HTMLElement | null>(null);
  const peekHistory = usePeekHistory();

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      data-ageval-scrim=""
      className="fixed inset-0 z-[60] flex items-center justify-center p-3 sm:p-6 bg-ink/40"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={setDialogEl}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-ageval-pop=""
        className={cn(
          "flex h-[min(92vh,900px)] w-[min(1120px,calc(100vw-1.5rem))] flex-col overflow-visible",
          "rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)]",
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <OverlayRootProvider value={dialogEl}>
          <div className="flex h-[4.5rem] shrink-0 items-center gap-3 px-4">
            <div ref={setHeadSlot} className="flex min-w-0 flex-1 items-center" />
            {peekHistory ? (
              <div className="flex shrink-0 items-center gap-0.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Back"
                  disabled={!peekHistory.canBack}
                  onClick={peekHistory.back}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Forward"
                  disabled={!peekHistory.canForward}
                  onClick={peekHistory.forward}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close"
              onClick={onClose}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <PageHeadSlotProvider slot={headSlot}>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
          </PageHeadSlotProvider>
        </OverlayRootProvider>
      </div>
    </div>,
    document.body,
  );
}
