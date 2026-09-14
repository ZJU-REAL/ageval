import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { OverlayRootProvider } from "@ageval/shared/components/overlay-root";
import { Button } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

/** Snapshot the opener before children `autoFocus`; restore only if still mounted. */
function useDialogFocus(
  open: boolean,
  onEscape: () => void,
  escapeBlocked?: () => boolean,
): RefObject<HTMLDivElement | null> {
  const panelRef = useRef<HTMLDivElement>(null);
  const onEscapeRef = useRef(onEscape);
  const blockedRef = useRef(escapeBlocked);
  const wasOpenRef = useRef(false);
  const restoreRef = useRef<HTMLElement | null>(null);
  onEscapeRef.current = onEscape;
  blockedRef.current = escapeBlocked;

  if (open !== wasOpenRef.current) {
    if (open) {
      const active = document.activeElement;
      restoreRef.current = active instanceof HTMLElement ? active : null;
    }
    wasOpenRef.current = open;
  }

  useLayoutEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const active = document.activeElement;
    if (panel && !(active instanceof Node && panel.contains(active))) {
      panel.focus();
    }
    return () => {
      const node = restoreRef.current;
      if (node?.isConnected) node.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (blockedRef.current?.()) return;
      onEscapeRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return panelRef;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  confirmVariant = "danger",
  busy = false,
  confirmDisabled = false,
  error = null,
  children,
  className,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: "danger" | "default";
  busy?: boolean;
  confirmDisabled?: boolean;
  error?: string | null;
  children?: ReactNode;
  className?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const titleId = useId();
  const descId = useId();
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const panelRef = useDialogFocus(open, onCancel, () => busyRef.current);
  const [host, setHost] = useState<HTMLElement | null>(null);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      data-ageval-scrim=""
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-ink/40"
      role="presentation"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <OverlayRootProvider value={host}>
      <div
        ref={(node) => {
          panelRef.current = node;
          setHost(node);
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={-1}
        data-ageval-pop=""
        className={cn(
          "w-full min-w-0 max-w-md overflow-hidden rounded-[14px] border border-hairline bg-canvas p-5 shadow-[var(--viewer-shadow-pop)] outline-none",
          className,
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <h2
          id={titleId}
          className="text-lg font-semibold tracking-tight text-ink"
        >
          {title}
        </h2>
        <div id={descId} className="mt-1 text-sm text-pretty break-words text-mute">
          {description}
        </div>
        {children ? <div className="mt-4">{children}</div> : null}
        {error ? (
          <p className="mt-3 text-sm font-mono text-error">{error}</p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={confirmVariant}
            disabled={busy || confirmDisabled}
            onClick={onConfirm}
          >
            {busy ? "…" : confirmLabel}
          </Button>
        </div>
      </div>
      </OverlayRootProvider>
    </div>,
    document.body,
  );
}

/** Content modal (share / settings). Close is the only chrome action. */
export function Modal({
  open,
  title,
  description,
  children,
  error = null,
  className,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  error?: string | null;
  className?: string;
  onClose: () => void;
}) {
  const titleId = useId();
  const descId = useId();
  const panelRef = useDialogFocus(open, onClose);
  const [host, setHost] = useState<HTMLElement | null>(null);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      data-ageval-scrim=""
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-ink/40"
      role="presentation"
      onClick={onClose}
    >
      <OverlayRootProvider value={host}>
      <div
        ref={(node) => {
          panelRef.current = node;
          setHost(node);
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        data-ageval-pop=""
        className={cn(
          "flex max-h-[min(90vh,40rem)] w-full min-w-0 max-w-md flex-col overflow-hidden rounded-[14px] border border-hairline bg-canvas p-5 shadow-[var(--viewer-shadow-pop)] outline-none",
          className,
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <h2
            id={titleId}
            className="min-w-0 flex-1 text-lg font-semibold tracking-tight text-ink"
          >
            {title}
          </h2>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close"
            className="-mr-1 -mt-1 h-8 w-8 text-mute"
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        {description ? (
          <div
            id={descId}
            className="mt-1 text-sm text-pretty break-words text-mute"
          >
            {description}
          </div>
        ) : null}
        {children ? (
          <div className="mt-4 min-w-0 overflow-y-auto">{children}</div>
        ) : null}
        {error ? (
          <p className="mt-3 text-sm font-mono text-error">{error}</p>
        ) : null}
      </div>
      </OverlayRootProvider>
    </div>,
    document.body,
  );
}
