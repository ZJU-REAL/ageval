/** Sidebar footer links. Empty env hides the item; unset uses the local default. */

const DEFAULT_GITHUB_URL = "https://github.com/ZJU-REAL/ageval";
const DEFAULT_DOCS_URL = "http://localhost:3000/en";

function readUrl(raw: unknown, fallback: string): string | null {
  if (typeof raw !== "string") return fallback;
  const value = raw.trim();
  if (!value) return null;
  return value;
}

export function githubRepoUrl(): string | null {
  return readUrl(import.meta.env.VITE_GITHUB_URL, DEFAULT_GITHUB_URL);
}

export function docsSiteUrl(): string | null {
  return readUrl(import.meta.env.VITE_DOCS_URL, DEFAULT_DOCS_URL);
}
