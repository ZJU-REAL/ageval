import { Info } from "lucide-react";

import { Button } from "@ageval/shared/components/ui/button";
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
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Error detail"
            onClick={(event) => event.stopPropagation()}
          >
            <Info className="h-4 w-4" aria-hidden />
          </Button>
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
