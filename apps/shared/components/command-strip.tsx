import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import { ShellCode } from "@ageval/shared/lib/shell-highlight";
import { cn } from "@ageval/shared/lib/utils";

export function CommandStrip({
  command,
  className,
}: {
  command: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-[10px] border border-hairline bg-code-bg px-3.5 py-2.5",
        className,
      )}
    >
      <pre
        className="flex-1 m-0 overflow-x-auto font-mono text-[13px] leading-5 whitespace-nowrap"
        aria-label="Shell command"
      >
        <code className="font-mono">
          <ShellCode command={command} />
        </code>
      </pre>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onCopy}
        aria-label="Copy command"
        className="shrink-0"
      >
        <span className="relative h-4 w-4">
          <Copy
            className={cn(
              "absolute inset-0 h-4 w-4 text-mute motion-safe:transition-[opacity,transform] motion-safe:duration-200 motion-safe:ease-smooth",
              copied ? "scale-50 opacity-0" : "scale-100 opacity-100",
            )}
          />
          <Check
            className={cn(
              "absolute inset-0 h-4 w-4 text-ink motion-safe:transition-[opacity,transform] motion-safe:duration-200 motion-safe:ease-spring",
              copied ? "scale-100 opacity-100" : "scale-50 opacity-0",
            )}
          />
        </span>
      </Button>
    </div>
  );
}
