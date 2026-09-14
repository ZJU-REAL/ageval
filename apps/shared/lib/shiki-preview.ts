/**
 * Shared Shiki highlighter for Hub file preview (multi-color syntax).
 * Lazy singleton — first paint may wait one tick for wasm/langs.
 */

import type { Highlighter } from "shiki";
import { createHighlighter } from "shiki";

const LANGS = [
  "python",
  "yaml",
  "json",
  "bash",
  "shellscript",
  "sql",
  "toml",
  "markdown",
  "typescript",
  "javascript",
  "tsx",
  "jsx",
  "rust",
  "dockerfile",
  "html",
  "css",
  "ini",
  "diff",
  "xml",
  "plaintext",
] as const;

let highlighterPromise: Promise<Highlighter> | null = null;

export function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ["github-dark", "github-light"],
      langs: [...LANGS],
    });
  }
  return highlighterPromise;
}

/** Map package path → Shiki language id. */
export function langFromPath(path: string | null | undefined): string {
  const lower = (path || "").toLowerCase();
  const base = lower.split("/").pop() || lower;

  if (base === "dockerfile" || base.endsWith(".dockerfile")) return "dockerfile";
  if (base === "makefile" || base.endsWith(".mk")) return "plaintext";

  if (lower.endsWith(".py") || lower.endsWith(".pyi")) return "python";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".json") || lower.endsWith(".jsonc")) return "json";
  if (lower.endsWith(".jsonl")) return "json"; // closest
  if (lower.endsWith(".sh") || lower.endsWith(".bash") || lower.endsWith(".zsh")) {
    return "bash";
  }
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".toml")) return "toml";
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
  if (lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".tsx")) return "tsx";
  if (lower.endsWith(".js") || lower.endsWith(".mjs") || lower.endsWith(".cjs")) {
    return "javascript";
  }
  if (lower.endsWith(".jsx")) return "jsx";
  if (lower.endsWith(".rs")) return "rust";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".xml")) return "xml";
  if (lower.endsWith(".diff") || lower.endsWith(".patch")) return "diff";
  if (lower.endsWith(".ini") || lower.endsWith(".cfg") || lower.endsWith(".conf")) {
    return "ini";
  }
  return "plaintext";
}

export function isMarkdownPath(path: string | null | undefined): boolean {
  const lower = (path || "").toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".markdown");
}

export async function codeToHtml(
  code: string,
  path: string | null | undefined,
  themeMode: "light" | "dark",
): Promise<string> {
  const highlighter = await getHighlighter();
  let lang = langFromPath(path);
  const loaded = highlighter.getLoadedLanguages();
  if (!loaded.includes(lang)) {
    lang = "plaintext";
  }
  const theme = themeMode === "dark" ? "github-dark" : "github-light";
  return highlighter.codeToHtml(code, {
    lang,
    theme,
  });
}
