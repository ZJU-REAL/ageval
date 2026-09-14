import { useEffect, useMemo, useState } from "react";

import { Markdown } from "@ageval/shared/components/markdown";
import { codeToHtml, isMarkdownPath } from "@ageval/shared/lib/shiki-preview";
import { useTheme } from "@ageval/shared/lib/theme";
import { cn } from "@ageval/shared/lib/utils";

/** Skip Shiki (and cap plain text) when content is huge — avoids main-thread stalls. */
const HIGHLIGHT_MAX_CHARS = 120_000;
const PLAIN_PREVIEW_MAX_CHARS = 400_000;

/**
 * Files-tab right pane: Markdown (GFM) for .md; Shiki multi-color for code.
 */
export function FilePreview({
  path,
  content,
  note,
}: {
  path: string | null;
  content: string;
  note?: string | null;
}) {
  const { resolved } = useTheme();
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const markdown = isMarkdownPath(path);
  const tooLargeForHighlight = content.length > HIGHLIGHT_MAX_CHARS;
  const displayContent = useMemo(() => {
    if (content.length <= PLAIN_PREVIEW_MAX_CHARS) return content;
    return (
      content.slice(0, PLAIN_PREVIEW_MAX_CHARS) +
      `\n\n… truncated for preview (${content.length.toLocaleString()} chars total)`
    );
  }, [content]);

  useEffect(() => {
    if (markdown || tooLargeForHighlight) {
      setHtml(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setHtml(null);
    setError(null);
    void codeToHtml(content, path, resolved)
      .then((out) => {
        if (!cancelled) setHtml(out);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          // plain fallback
          setHtml(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [content, path, resolved, markdown, tooLargeForHighlight]);

  if (markdown) {
    const mdSource =
      content.length > PLAIN_PREVIEW_MAX_CHARS
        ? content.slice(0, PLAIN_PREVIEW_MAX_CHARS) +
          `\n\n… truncated for preview (${content.length.toLocaleString()} chars total)`
        : content;
    return (
      <div className="p-4 overflow-auto h-full min-h-full bg-canvas">
        {note ? <p className="text-xs text-mute mb-2">{note}</p> : null}
        {content.length > PLAIN_PREVIEW_MAX_CHARS ? (
          <p className="text-xs text-mute mb-2">
            Large file — showing first {PLAIN_PREVIEW_MAX_CHARS.toLocaleString()}{" "}
            characters.
          </p>
        ) : null}
        <Markdown source={mdSource} className="border-0 rounded-none p-0" />
      </div>
    );
  }

  if (tooLargeForHighlight || error) {
    return (
      <div className="h-full overflow-auto">
        {tooLargeForHighlight ? (
          <p className="text-xs text-mute px-3 pt-3">
            Large file ({content.length.toLocaleString()} chars) — plain preview
            without syntax highlighting
            {content.length > PLAIN_PREVIEW_MAX_CHARS
              ? `, first ${PLAIN_PREVIEW_MAX_CHARS.toLocaleString()} chars`
              : ""}
            .
          </p>
        ) : null}
        {note ? <p className="text-xs text-mute px-3 pt-2">{note}</p> : null}
        <pre
          className={cn(
            "m-0 p-3 min-h-full overflow-auto",
            "whitespace-pre-wrap break-words font-mono text-[12px] leading-5",
            "bg-code-bg text-shell-plain",
          )}
        >
          {displayContent}
        </pre>
      </div>
    );
  }

  if (!html) {
    return <p className="text-sm text-mute p-3">Highlighting…</p>;
  }

  return (
    <div className="h-full overflow-auto bg-code-bg">
      {note ? <p className="text-xs text-mute px-3 pt-2">{note}</p> : null}
      <div
        className="shiki-preview text-[12px] leading-5 [&_pre]:m-0 [&_pre]:p-3 [&_pre]:overflow-x-auto [&_pre]:!bg-transparent [&_code]:font-mono [&_code]:text-[12px] [&_code]:leading-5"
        // Shiki trusts its own HTML; content is package file body (operator-controlled).
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
