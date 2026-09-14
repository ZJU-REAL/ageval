import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import { codeToHtml } from "@ageval/shared/lib/shiki-preview";
import { useTheme } from "@ageval/shared/lib/theme";
import { cn } from "@ageval/shared/lib/utils";

/**
 * Copyable fenced file (Shiki from path). Hairline + code-bg, same chrome as
 * CommandStrip — not the lightweight tokenizer used in trial file panes.
 */
export function CodeFence({
  path,
  content,
  className,
  maxHeightClass = "max-h-56",
}: {
  path: string;
  content: string;
  className?: string;
  maxHeightClass?: string;
}) {
  const { resolved } = useTheme();
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    void codeToHtml(content, path, resolved)
      .then((out) => {
        if (!cancelled) setHtml(out);
      })
      .catch(() => {
        if (!cancelled) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [content, path, resolved]);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[10px] border border-hairline bg-code-bg",
        className,
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onCopy}
        aria-label="Copy"
        className="absolute right-1.5 top-1.5 z-10 h-7 w-7 shrink-0"
      >
        <span className="relative h-3.5 w-3.5">
          <Copy
            className={cn(
              "absolute inset-0 h-3.5 w-3.5 text-mute motion-safe:transition-[opacity,transform] motion-safe:duration-200 motion-safe:ease-smooth",
              copied ? "scale-50 opacity-0" : "scale-100 opacity-100",
            )}
          />
          <Check
            className={cn(
              "absolute inset-0 h-3.5 w-3.5 text-ink motion-safe:transition-[opacity,transform] motion-safe:duration-200 motion-safe:ease-spring",
              copied ? "scale-100 opacity-100" : "scale-50 opacity-0",
            )}
          />
        </span>
      </Button>
      {html ? (
        <div
          className={cn(
            "overflow-auto shiki-preview text-[12px] leading-5",
            "[&_pre]:m-0 [&_pre]:p-3 [&_pre]:pr-10 [&_pre]:overflow-x-auto [&_pre]:!bg-transparent",
            "[&_code]:font-mono [&_code]:text-[12px] [&_code]:leading-5",
            maxHeightClass,
          )}
          // Shiki trusts its own HTML; content is generated profiles / CLI text.
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre
          className={cn(
            "m-0 overflow-auto p-3 pr-10 font-mono text-[12px] leading-5 whitespace-pre",
            maxHeightClass,
          )}
        >
          <code className="font-mono">{content}</code>
        </pre>
      )}
    </div>
  );
}
