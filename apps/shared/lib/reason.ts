/** Filter key for an Attempt row: the error title, a legacy string, or the reached limit. */

export type ErrorRecord = {
  phase?: string | null;
  title?: string;
  message?: string;
};

export type ErrorValue = string | ErrorRecord | null;

export type ErrorFields = {
  title: string;
  message: string;
};

export function reasonText(row: {
  status?: string | null;
  error?: unknown;
  limit?: string | null;
}): string {
  const status = (row.status || "").toUpperCase();
  const fromError = status === "ERROR" || present(row.error);
  if (fromError) {
    const fields = errorFields(row.error);
    if (fields?.title) return fields.title;
    if (fields?.message) return fields.message;
    return plainError(row.error);
  }
  if (typeof row.limit === "string" && row.limit.trim()) return row.limit.trim();
  return "";
}

/** Title and message when `error` is a record. A string stays a string. */
export function errorFields(error: unknown): ErrorFields | null {
  if (!error || typeof error !== "object" || Array.isArray(error)) return null;
  const record = error as ErrorRecord;
  const title = typeof record.title === "string" ? record.title.trim() : "";
  const message = typeof record.message === "string" ? record.message.trim() : "";
  if (!title && !message) return null;
  return { title, message: message && message !== title ? message : "" };
}

export function distinctReasons<T>(
  rows: readonly T[],
  text: (row: T) => string,
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of rows) {
    const value = text(row);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

function present(error: unknown): boolean {
  if (error == null || error === "") return false;
  return typeof error === "string" || typeof error === "object";
}

function plainError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    try {
      return JSON.stringify(error);
    } catch {
      return String(error);
    }
  }
  if (error == null || error === "") return "";
  return String(error);
}
