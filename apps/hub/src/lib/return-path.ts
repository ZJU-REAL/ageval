const RETURN_KEY = "ageval-hub-return";

export function rememberReturnPath(path: string): void {
  try {
    sessionStorage.setItem(RETURN_KEY, path);
  } catch {
    /* ignore */
  }
}

export function takeReturnPath(fallback = "/leaderboard"): string {
  try {
    const raw = sessionStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    if (raw && raw.startsWith("/")) return raw;
  } catch {
    /* ignore */
  }
  return fallback;
}
