import type { Components } from "react-markdown";
import { useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { splitMarkdownFrontmatter } from "@/lib/markdown-frontmatter";
import { codeToHtml } from "@/lib/shiki-preview";
import { useTheme } from "@/lib/theme";
import { EXTERNAL_LINK_CLASS } from "@/lib/links";
import { cn } from "@/lib/utils";

function FencedCode({ lang, text }: { lang: string; text: string }) {
  const { resolved } = useTheme();
  const [html, setHtml] = useState<string | null>(null);
  const fakePath =
    lang === "python" || lang === "py"
      ? "x.py"
      : lang === "yaml" || lang === "yml"
        ? "x.yaml"
        : lang === "json"
          ? "x.json"
          : lang === "bash" || lang === "sh" || lang === "shell"
            ? "x.sh"
            : lang === "sql"
              ? "x.sql"
              : lang === "toml"
                ? "x.toml"
                : lang === "ts" || lang === "typescript"
                  ? "x.ts"
                  : lang === "js" || lang === "javascript"
                    ? "x.js"
                    : "x.txt";

  useEffect(() => {
    let cancelled = false;
    void codeToHtml(text, fakePath, resolved).then((out) => {
      if (!cancelled) setHtml(out);
    });
    return () => {
      cancelled = true;
    };
  }, [text, fakePath, resolved]);

  if (!html) {
    return (
      <pre
        className={cn(
          "my-3 overflow-x-auto blob-panel",
          "bg-code-bg p-3 font-mono text-[12px] leading-5",
        )}
      >
        <code className="font-mono">{text}</code>
      </pre>
    );
  }

  return (
    <div
      className={cn(
        "my-3 overflow-x-auto blob-panel",
        "bg-code-bg text-[12px] leading-5",
        "[&_pre]:m-0 [&_pre]:p-3 [&_pre]:!bg-transparent [&_code]:font-mono",
      )}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function isHttpUrl(href: string | undefined): href is string {
  if (!href) return false;
  try {
    const url = new URL(href);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function MarkdownLink({
  href,
  children,
}: {
  href?: string;
  children?: ReactNode;
}) {
  if (!isHttpUrl(href)) {
    return <span>{children}</span>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={EXTERNAL_LINK_CLASS}
    >
      {children}
    </a>
  );
}

const INLINE_ELEMENTS = ["p", "a", "strong", "em", "code"] as const;

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-xl font-semibold tracking-tight text-ink mt-6 mb-3 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-lg font-semibold tracking-tight text-ink mt-5 mb-2 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-base font-semibold text-ink mt-4 mb-2 first:mt-0">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="min-w-0 text-sm text-body leading-6 mb-3 last:mb-0 break-words">
      {children}
    </p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc pl-5 mb-3 space-y-1 text-sm text-body">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal pl-5 mb-3 space-y-1 text-sm text-body">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-6">{children}</li>,
  a: MarkdownLink,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-hairline-strong pl-3 my-3 text-sm text-mute">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-hairline my-4" />,
  strong: ({ children }) => (
    <strong className="font-semibold text-ink">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  code: ({ className, children }) => {
    const isBlock = Boolean(className);
    const text = String(children).replace(/\n$/, "");
    if (!isBlock) {
      return (
        <code className="max-w-full whitespace-pre-wrap break-all font-mono text-[12px] bg-canvas-soft-2 text-ink px-1 py-0.5 rounded-[4px]">
          {text}
        </code>
      );
    }
    const lang = (className || "").replace(/^language-/, "") || "text";
    return <FencedCode lang={lang} text={text} />;
  },
  pre: ({ children }) => <>{children}</>,
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto blob-panel">
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-canvas-soft">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-hairline last:border-0">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-sm font-medium text-mute align-top whitespace-nowrap">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2 text-sm text-body align-top">{children}</td>
  ),
};

function FrontmatterTable({ fields }: { fields: { key: string; value: string }[] }) {
  if (!fields.length) return null;
  return (
    <dl className="mb-4 blob-panel overflow-hidden">
      {fields.map((field) => (
        <div
          key={field.key}
          className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 px-3 py-2 border-b border-hairline last:border-0"
        >
          <dt className="font-mono text-[11px] text-mute pt-0.5">{field.key}</dt>
          <dd className="m-0 text-sm text-body whitespace-pre-wrap break-words">
            {field.value || "—"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** One paragraph of Hub copy. Markdown links only; no card, no headings. */
export function InlineMarkdown({
  source,
  className,
}: {
  source: string;
  className?: string;
}) {
  return (
    <div className={cn("text-sm text-body max-w-4xl [&_p]:mb-0", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        allowedElements={[...INLINE_ELEMENTS]}
        unwrapDisallowed
        components={{
          p: ({ children }) => (
            <p className="text-sm text-body leading-6">{children}</p>
          ),
          a: MarkdownLink,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          code: ({ children }) => (
            <code className="max-w-full whitespace-pre-wrap break-all font-mono text-[12px] bg-canvas-soft-2 text-ink px-1 py-0.5 rounded-[4px]">
              {String(children).replace(/\n$/, "")}
            </code>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

/** Markdown render without the panel chrome; shared by docs and step bodies. */
export function MarkdownBody({
  source,
  className,
}: {
  source: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 max-w-none", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}

export function Markdown({
  source,
  className,
}: {
  source: string;
  className?: string;
}) {
  const { fields, body } = splitMarkdownFrontmatter(source);
  return (
    <div
      className={cn(
        "blob-panel min-w-0 p-5 max-w-none",
        className,
      )}
    >
      <FrontmatterTable fields={fields} />
      {body.trim() ? <MarkdownBody source={body} /> : null}
    </div>
  );
}
