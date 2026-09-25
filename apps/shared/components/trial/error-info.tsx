import { Info } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@ageval/shared/components/ui/tooltip";
import { errorFields } from "@ageval/shared/lib/reason";

function tipText(error: unknown): string {
  if (typeof error === "string") return error.trim();
  if (error && typeof error === "object") {
    try {
      const text = JSON.stringify(error);
      return text && text !== "{}" ? text : "";
    } catch {
      return String(error);
    }
  }
  return "";
}

/** Hover detail for an ERROR status. Title, then the message. */
export function ErrorInfo({ error }: { error: unknown }) {
  const fields = errorFields(error);
  const title = fields?.title ?? "";
  const message = fields?.message || (!fields ? tipText(error) : "");
  if (!title && !message) return null;
  return (
    <TooltipProvider delayDuration={80}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="Error detail"
            className="inline-flex rounded-[8px] text-mute hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70"
            onClick={(event) => event.stopPropagation()}
          >
            <Info className="h-3.5 w-3.5" aria-hidden />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-sm px-3 py-2 text-sm leading-5">
          {title ? <span className="block font-semibold text-error">{title}</span> : null}
          {message ? (
            <span
              className={
                title
                  ? "mt-1 block whitespace-pre-wrap break-words text-body"
                  : "block whitespace-pre-wrap break-words text-body"
              }
            >
              {message}
            </span>
          ) : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
