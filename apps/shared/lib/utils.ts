import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Locked package identity. Empty when either side is missing. */
export function datasetRef(
  id?: string | null,
  version?: string | null,
): string | null {
  const a = (id || "").trim();
  const b = (version || "").trim();
  if (!a || !b) return null;
  return `${a}@${b}`;
}

export function formatScore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return Number(value).toFixed(2);
}

/** Jobs / Hub axis: ``a+b+c`` → ``a+...``; tooltip keeps the full string. */
export function formatAxisLabel(raw: string | null | undefined): {
  text: string;
  title?: string;
} {
  const value = (raw || "").trim();
  if (!value) return { text: "-" };
  const parts = value.split("+").map((s) => s.trim()).filter(Boolean);
  if (parts.length <= 1) return { text: value, title: value };
  return { text: `${parts[0]}+...`, title: parts.join("+") };
}

export function lastModelSegment(raw: string): string {
  const value = raw.trim();
  if (!value) return "";
  const bits = value.split("/");
  return (bits[bits.length - 1] || value).trim();
}

/** Short model: last ``/`` segment, optional ``[effort]``. Tooltip is the full name. */
export function formatModelLabel(
  raw: string | null | undefined,
  effort?: string | null,
): { text: string; title: string } {
  const value = (raw || "").trim();
  if (!value) return { text: "-", title: "" };
  const parts = value.split("+").map((s) => s.trim()).filter(Boolean);
  const short = parts.map(lastModelSegment).filter(Boolean);
  let text =
    short.length <= 1 ? short[0] || value : `${short[0]}+...`;
  const extra = (effort || "").trim();
  if (extra) text = `${text}[${extra}]`;
  return { text, title: value };
}

export function reasoningEffortFromBinding(binding: unknown): string {
  if (!binding || typeof binding !== "object") return "";
  const rec = binding as Record<string, unknown>;
  const fromOpts = (opts: unknown): string => {
    let raw = opts;
    if (typeof raw === "string" && raw.trim().startsWith("{")) {
      try {
        raw = JSON.parse(raw) as unknown;
      } catch {
        return "";
      }
    }
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "";
    const val = (raw as Record<string, unknown>).reasoning_effort;
    return typeof val === "string" && val.trim() ? val.trim() : "";
  };
  const top = fromOpts(rec.options);
  if (top) return top;
  const ext = rec.extensions;
  if (Array.isArray(ext)) {
    for (const item of ext) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      if (String(row.plugin || "") === "acp") {
        const hit = fromOpts(row.options);
        if (hit) return hit;
      }
    }
    for (const item of ext) {
      if (!item || typeof item !== "object") continue;
      const hit = fromOpts((item as Record<string, unknown>).options);
      if (hit) return hit;
    }
  }
  return "";
}

function acpEntryFromProfile(profile: Record<string, unknown>): string {
  const sources: unknown[] = [profile.options];
  const extensions = profile.extensions;
  if (Array.isArray(extensions)) {
    for (const item of extensions) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      if (String(row.plugin || "") === "acp") sources.push(row.options);
    }
  }
  for (const source of sources) {
    if (!source || typeof source !== "object" || Array.isArray(source)) continue;
    const entry = (source as Record<string, unknown>).entry;
    if (typeof entry === "string" && entry.trim()) return entry.trim();
  }
  return "";
}

/** Product id: ACP entry, else a non-transport executor. Empty for transport-only acp. */
export function resolveHarnessId(profile: unknown): string {
  if (!profile || typeof profile !== "object") return "";
  const rec = profile as Record<string, unknown>;
  const executor = String(rec.executor || "").trim();
  if (executor === "acp") return acpEntryFromProfile(rec);
  return executor;
}

/** Unique overlay harness ids, in profile order. */
export function overlayHarnessIds(overlay: unknown): string[] {
  if (!overlay || typeof overlay !== "object") return [];
  const profiles = (overlay as Record<string, unknown>).agent_profiles;
  if (!profiles || typeof profiles !== "object") return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of Object.values(profiles as Record<string, unknown>)) {
    const id = resolveHarnessId(raw);
    const key = id.toLowerCase();
    if (!id || seen.has(key)) continue;
    seen.add(key);
    out.push(id);
  }
  return out;
}

/** Jobs Agent axis from job_overlay.agent_profiles (label → ACP entry → executor). */
export function displayAgentName(profile: unknown): string {
  if (!profile || typeof profile !== "object") return "";
  const rec = profile as Record<string, unknown>;
  const label = rec.label;
  if (typeof label === "string" && label.trim()) return label.trim();
  const projected = rec.entry;
  if (typeof projected === "string" && projected.trim()) return projected.trim();
  const executor = String(rec.executor || "").trim();
  if (executor === "acp") return acpEntryFromProfile(rec) || executor;
  return executor;
}

export function displayLabelsFromOverlay(overlay: unknown): {
  agent: string;
  model: string;
} {
  if (!overlay || typeof overlay !== "object") return { agent: "", model: "" };
  const profiles = (overlay as Record<string, unknown>).agent_profiles;
  if (!profiles || typeof profiles !== "object") return { agent: "", model: "" };
  const agents: string[] = [];
  const models: string[] = [];
  for (const raw of Object.values(profiles as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object") continue;
    const rec = raw as Record<string, unknown>;
    const name = displayAgentName(rec);
    if (name) agents.push(name);
    const model = rec.model;
    models.push(typeof model === "string" ? model.trim() : "");
  }
  const join = (values: string[]) => {
    const cleaned = values.filter(Boolean);
    if (!cleaned.length) return "";
    if (new Set(cleaned).size === 1) return cleaned[0];
    return cleaned.join("+");
  };
  return { agent: join(agents), model: join(models) };
}

export function reasoningEffortFromOverlay(overlay: unknown): string {
  if (!overlay || typeof overlay !== "object") return "";
  const profiles = (overlay as Record<string, unknown>).agent_profiles;
  if (!profiles || typeof profiles !== "object") return "";
  const found: string[] = [];
  for (const raw of Object.values(profiles as Record<string, unknown>)) {
    const effort = reasoningEffortFromBinding(raw);
    if (effort) found.push(effort);
  }
  if (!found.length) return "";
  if (new Set(found).size === 1) return found[0];
  return found.join("+");
}

export function formatTrials(done: number | null | undefined, total: number | null | undefined): string {
  if (total == null) return "-";
  return `${done ?? 0}/${total}`;
}

function parseDisplayDate(iso: string | number | null | undefined): Date | null {
  if (iso == null || iso === "") return null;
  try {
    const d =
      typeof iso === "number"
        ? new Date(iso < 1e12 ? iso * 1000 : iso)
        : new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

export function formatCount(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0";
  const value = Math.floor(n);
  if (value < 1000) return String(value);
  if (value < 1_000_000) {
    const k = value / 1000;
    return `${(k >= 10 ? k.toFixed(0) : k.toFixed(1)).replace(/\.0$/, "")}k`;
  }
  const m = value / 1_000_000;
  return `${(m >= 10 ? m.toFixed(0) : m.toFixed(1)).replace(/\.0$/, "")}m`;
}

export function formatDay(
  iso: string | number | null | undefined,
): string {
  const d = parseDisplayDate(iso);
  if (!d) return iso == null || iso === "" ? "-" : String(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}/${m}/${day}`;
}

export function formatDate(
  iso: string | number | null | undefined,
): string {
  const d = parseDisplayDate(iso);
  if (!d) return iso == null || iso === "" ? "-" : String(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${formatDay(iso)} ${hh}:${mm}`;
}

/** Coerce API error fields to a string for React children (objects crash React #31). */
export function formatError(value: unknown): string {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function formatBytes(value: number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "-";
  if (n < 1024) return `${Math.round(n)} B`;
  const units = ["KB", "MB", "GB"];
  let amount = n / 1024;
  let unit = units[0];
  for (const next of units.slice(1)) {
    if (amount < 1024) break;
    amount /= 1024;
    unit = next;
  }
  const digits = amount < 10 ? 1 : 0;
  return `${amount.toFixed(digits)} ${unit}`;
}
