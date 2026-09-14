/**
 * Lightweight file preview highlighter (no language server).
 * JSON/JSONL plus Python/YAML/shell so Verifier script view is not plain text.
 */
import type { ReactNode } from "react";

type Kind =
  | "key"
  | "string"
  | "number"
  | "bool"
  | "null"
  | "punct"
  | "plain"
  | "comment"
  | "kw";

type Token = { kind: Kind; text: string };

const KIND_CLASS: Record<Kind, string> = {
  key: "text-shell-flag",
  string: "text-shell-string",
  number: "text-shell-cmd",
  bool: "text-shell-path",
  null: "text-shell-path",
  punct: "text-shell-punct",
  plain: "text-shell-plain",
  comment: "text-shell-punct italic",
  kw: "text-shell-cmd",
};

const PY_KW = new Set(
  "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case".split(
    " ",
  ),
);

const SH_KW = new Set(
  "if then else elif fi for while do done case esac in function select until export local return break continue".split(
    " ",
  ),
);

function tokenizeJson(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  let expectingKey = false;
  const stack: string[] = []; // track object vs array for key detection

  const peek = () => src[i];
  const push = (kind: Kind, text: string) => {
    tokens.push({ kind, text });
  };

  while (i < src.length) {
    const ch = peek();

    // whitespace
    if (/\s/.test(ch)) {
      let j = i + 1;
      while (j < src.length && /\s/.test(src[j])) j += 1;
      push("plain", src.slice(i, j));
      i = j;
      continue;
    }

    // punctuation
    if (ch === "{" || ch === "}" || ch === "[" || ch === "]" || ch === ":" || ch === ",") {
      if (ch === "{") {
        stack.push("obj");
        expectingKey = true;
      } else if (ch === "[") {
        stack.push("arr");
        expectingKey = false;
      } else if (ch === "}" || ch === "]") {
        stack.pop();
        expectingKey = stack[stack.length - 1] === "obj";
      } else if (ch === ":") {
        expectingKey = false;
      } else if (ch === ",") {
        expectingKey = stack[stack.length - 1] === "obj";
      }
      push("punct", ch);
      i += 1;
      continue;
    }

    // string
    if (ch === '"') {
      let j = i + 1;
      while (j < src.length) {
        if (src[j] === "\\") {
          j += 2;
          continue;
        }
        if (src[j] === '"') {
          j += 1;
          break;
        }
        j += 1;
      }
      const text = src.slice(i, j);
      // key if we are in object and expecting a key
      const isKey = expectingKey && stack[stack.length - 1] === "obj";
      push(isKey ? "key" : "string", text);
      i = j;
      continue;
    }

    // number
    if (/[0-9-]/.test(ch)) {
      let j = i + 1;
      while (j < src.length && /[0-9.eE+-]/.test(src[j])) j += 1;
      push("number", src.slice(i, j));
      i = j;
      continue;
    }

    // true / false / null
    if (src.startsWith("true", i)) {
      push("bool", "true");
      i += 4;
      continue;
    }
    if (src.startsWith("false", i)) {
      push("bool", "false");
      i += 5;
      continue;
    }
    if (src.startsWith("null", i)) {
      push("null", "null");
      i += 4;
      continue;
    }

    // fallback single char
    push("plain", ch);
    i += 1;
  }

  return tokens;
}

function tokenizeSource(
  src: string,
  opts: { keywords: Set<string>; lineComment?: string; hashComment?: boolean },
): Token[] {
  const tokens: Token[] = [];
  const lines = src.split("\n");
  const lineComment = opts.lineComment;

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    let i = 0;
    if (opts.hashComment) {
      const trimmed = line.trimStart();
      if (trimmed.startsWith("#")) {
        tokens.push({ kind: "comment", text: line });
        if (li < lines.length - 1) tokens.push({ kind: "plain", text: "\n" });
        continue;
      }
    }
    while (i < line.length) {
      const ch = line[i];
      if (lineComment && line.startsWith(lineComment, i)) {
        tokens.push({ kind: "comment", text: line.slice(i) });
        i = line.length;
        continue;
      }
      if (opts.hashComment && ch === "#") {
        tokens.push({ kind: "comment", text: line.slice(i) });
        i = line.length;
        continue;
      }
      if (/\s/.test(ch)) {
        let j = i + 1;
        while (j < line.length && /\s/.test(line[j])) j += 1;
        tokens.push({ kind: "plain", text: line.slice(i, j) });
        i = j;
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") {
        const quote = ch;
        let j = i + 1;
        if (
          (quote === '"' || quote === "'") &&
          line.startsWith(quote + quote + quote, i)
        ) {
          const delim = quote + quote + quote;
          const close = line.indexOf(delim, i + 3);
          if (close >= 0) {
            j = close + 3;
            tokens.push({ kind: "string", text: line.slice(i, j) });
            i = j;
            continue;
          }
          tokens.push({ kind: "string", text: line.slice(i) });
          i = line.length;
          continue;
        }
        while (j < line.length) {
          if (line[j] === "\\") {
            j += 2;
            continue;
          }
          if (line[j] === quote) {
            j += 1;
            break;
          }
          j += 1;
        }
        tokens.push({ kind: "string", text: line.slice(i, j) });
        i = j;
        continue;
      }
      if (/[0-9]/.test(ch) || (ch === "." && /[0-9]/.test(line[i + 1] || ""))) {
        let j = i + 1;
        while (j < line.length && /[0-9.xXa-fA-F_]/.test(line[j])) j += 1;
        tokens.push({ kind: "number", text: line.slice(i, j) });
        i = j;
        continue;
      }
      if (/[A-Za-z_]/.test(ch)) {
        let j = i + 1;
        while (j < line.length && /[A-Za-z0-9_]/.test(line[j])) j += 1;
        const word = line.slice(i, j);
        const lower = word.toLowerCase();
        tokens.push({
          kind: opts.keywords.has(word) || opts.keywords.has(lower) ? "kw" : "plain",
          text: word,
        });
        i = j;
        continue;
      }
      tokens.push({ kind: "punct", text: ch });
      i += 1;
    }
    if (li < lines.length - 1) tokens.push({ kind: "plain", text: "\n" });
  }
  return tokens;
}

function tryPrettyJson(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  if (!(t.startsWith("{") || t.startsWith("["))) return null;
  try {
    return JSON.stringify(JSON.parse(t), null, 2);
  } catch {
    return null;
  }
}

function formatJsonl(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const s = line.trim();
      if (!s) return line;
      try {
        return JSON.stringify(JSON.parse(s));
      } catch {
        return line;
      }
    })
    .join("\n");
}

export type CodeLang = "json" | "jsonl" | "python" | "yaml" | "shell" | "text";

export function detectLang(path: string | null | undefined, content: string): CodeLang {
  const lower = (path || "").toLowerCase();
  if (lower.endsWith(".jsonl")) return "jsonl";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".py") || lower.endsWith(".pyi")) return "python";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (
    lower.endsWith(".sh") ||
    lower.endsWith(".bash") ||
    lower.endsWith(".zsh")
  ) {
    return "shell";
  }
  // Heuristic for content without extension
  const t = content.trim();
  if (t.startsWith("{") || t.startsWith("[")) {
    try {
      JSON.parse(t);
      return "json";
    } catch {
      /* fall through */
    }
  }
  // multi-line json objects often jsonl
  const lines = t.split("\n").filter((l) => l.trim());
  if (lines.length > 1 && lines.every((l) => l.trim().startsWith("{"))) {
    return "jsonl";
  }
  return "text";
}

export function preparePreview(
  path: string | null | undefined,
  content: string,
): { lang: CodeLang; text: string } {
  const lang = detectLang(path, content);
  if (lang === "json") {
    const pretty = tryPrettyJson(content);
    return { lang, text: pretty ?? content };
  }
  if (lang === "jsonl") {
    return { lang, text: formatJsonl(content) };
  }
  return { lang, text: content };
}

/** Skip tokenization for huge bodies (caller may also pre-truncate). */
const HIGHLIGHT_MAX_CHARS = 120_000;

export function CodeHighlight({
  path,
  content,
}: {
  path?: string | null;
  content: string;
}): ReactNode {
  if (content.length > HIGHLIGHT_MAX_CHARS) {
    return <span className="text-shell-plain">{content}</span>;
  }

  const { lang, text } = preparePreview(path, content);

  if (lang === "text") {
    return <span className="text-shell-plain">{text}</span>;
  }

  if (lang === "python") {
    const tokens = tokenizeSource(text, { keywords: PY_KW, lineComment: "#" });
    return (
      <>
        {tokens.map((t, idx) => (
          <span key={`${idx}-${t.kind}`} className={KIND_CLASS[t.kind]}>
            {t.text}
          </span>
        ))}
      </>
    );
  }
  if (lang === "yaml") {
    const tokens = tokenizeSource(text, { keywords: new Set(), hashComment: true });
    return (
      <>
        {tokens.map((t, idx) => (
          <span key={`${idx}-${t.kind}`} className={KIND_CLASS[t.kind]}>
            {t.text}
          </span>
        ))}
      </>
    );
  }
  if (lang === "shell") {
    const tokens = tokenizeSource(text, { keywords: SH_KW, hashComment: true });
    return (
      <>
        {tokens.map((t, idx) => (
          <span key={`${idx}-${t.kind}`} className={KIND_CLASS[t.kind]}>
            {t.text}
          </span>
        ))}
      </>
    );
  }

  // jsonl: highlight each non-empty line independently so broken lines stay readable
  if (lang === "jsonl") {
    const lines = text.split("\n");
    return (
      <>
        {lines.map((line, li) => {
          if (!line.trim()) {
            return (
              <span key={li} className="text-shell-plain">
                {"\n"}
              </span>
            );
          }
          const tokens = tokenizeJson(line);
          return (
            <span key={li}>
              {tokens.map((t, ti) => (
                <span key={`${li}-${ti}`} className={KIND_CLASS[t.kind]}>
                  {t.text}
                </span>
              ))}
              {li < lines.length - 1 ? "\n" : null}
            </span>
          );
        })}
      </>
    );
  }

  const tokens = tokenizeJson(text);
  return (
    <>
      {tokens.map((t, idx) => (
        <span key={`${idx}-${t.kind}`} className={KIND_CLASS[t.kind]}>
          {t.text}
        </span>
      ))}
    </>
  );
}
