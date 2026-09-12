export const appName = "ageval";
export const docsRoute = "/docs";

export const gitConfig = {
  user: "ZJU-REAL",
  repo: "ageval",
  branch: "main",
};

/** Hub SPA origin. Unset = local Vite default; empty string hides the link. */
const DEFAULT_HUB_URL = "http://127.0.0.1:5174";

export function hubSiteUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_HUB_URL;
  if (typeof raw !== "string") return DEFAULT_HUB_URL;
  const value = raw.trim();
  if (!value) return null;
  return value;
}

/** `NEXT_PUBLIC_BASE_PATH` without a trailing slash. Empty on a domain root. */
export function siteBasePath(): string {
  const raw = process.env.NEXT_PUBLIC_BASE_PATH?.trim() ?? "";
  if (!raw || raw === "/") return "";
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

/** Prefix a site-relative page path (`/en/docs`) for `basePath` + trailingSlash. */
export function sitePath(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const withSlash = p.endsWith("/") ? p : `${p}/`;
  return `${siteBasePath()}${withSlash}`;
}

/** Prefix a public asset (`/images/…`). No trailing slash. */
export function assetPath(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${siteBasePath()}${p}`;
}
