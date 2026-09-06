import {
  useEffect,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

/** Glass search dialog shell (Models Cmd/Ctrl+F, attach pickers). */
export function SearchPalette({
  open,
  onClose,
  label,
  query,
  onQuery,
  placeholder,
  countLabel,
  children,
  empty,
  inputRef,
  listRef,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  query: string;
  onQuery: (next: string) => void;
  placeholder: string;
  countLabel?: string;
  children: ReactNode;
  empty?: ReactNode;
  inputRef?: RefObject<HTMLInputElement | null>;
  listRef?: RefObject<HTMLDivElement | null>;
}) {
  useEffect(() => {
    if (!open) return;
    inputRef?.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, inputRef]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      data-ageval-scrim=""
      className="fixed inset-0 z-[80] flex items-center justify-center bg-ink/30 p-3 backdrop-blur-sm sm:p-6"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        data-ageval-pop=""
        className={cn(
          "flex w-[min(760px,100%)] flex-col overflow-hidden",
          "rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)]",
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-hairline px-4">
          <Search className="h-4 w-4 shrink-0 text-mute" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder={placeholder}
            aria-label={label}
            autoComplete="off"
            spellCheck={false}
            className="h-12 min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-mute"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close search"
            className="shrink-0 rounded-[6px] border border-hairline px-1.5 py-0.5 text-xs text-mute transition-colors duration-200 ease-smooth hover:text-ink"
          >
            Esc
          </button>
        </div>
        <div
          ref={listRef}
          role="listbox"
          aria-label={label}
          className="max-h-[min(56vh,460px)] overflow-y-auto p-2"
        >
          {countLabel ? (
            <p className="px-2 pb-1.5 pt-1 text-sm font-medium text-ink">
              {countLabel}
            </p>
          ) : null}
          {children}
          {empty}
        </div>
      </div>
    </div>,
    document.body,
  );
}
