import type { ModelJoin, ModelPin, PinnedModel } from "./types";

/** Overlay invoke id as run — do not strip prefixes in yaml. */
export function joinOverlay(overlay: string, pin: ModelPin | null | undefined): ModelJoin {
  const text = overlay.trim();
  if (!text) return { overlay: text, canonical: null, hits: [] };
  if (!pin) return { overlay: text, canonical: null, hits: [] };

  const alias = (pin.aliases[text] || "").trim();
  if (alias && pin.models[alias]) {
    return { overlay: text, canonical: alias, hits: [alias] };
  }

  const collected: string[] = [];
  const seen = new Set<string>();
  for (const candidate of overlayCandidates(text, pin.prefixes)) {
    const ids = pin.lookup[candidate];
    if (!ids || ids.length === 0) continue;
    const unique: string[] = [];
    const local = new Set<string>();
    for (const id of ids) {
      if (!pin.models[id] || local.has(id)) continue;
      local.add(id);
      unique.push(id);
    }
    if (unique.length === 1) {
      return { overlay: text, canonical: unique[0] ?? null, hits: unique };
    }
    for (const id of unique) {
      if (seen.has(id)) continue;
      seen.add(id);
      collected.push(id);
    }
  }
  return { overlay: text, canonical: null, hits: collected };
}

export function overlayCandidates(overlay: string, prefixes: readonly string[]): string[] {
  const text = overlay.trim();
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (value: string) => {
    const next = value.trim().replace(/^\/+|\/+$/g, "");
    if (!next || seen.has(next)) return;
    seen.add(next);
    out.push(next);
  };
  add(text);
  const once = peelPrefix(text, prefixes);
  if (once) {
    add(once);
    const twice = peelPrefix(once, prefixes);
    if (twice) add(twice);
  }
  const parts = text.split("/").filter(Boolean);
  if (parts.length >= 1) add(parts[parts.length - 1] ?? "");
  if (parts.length >= 2) add(parts.slice(-2).join("/"));
  return out;
}

function peelPrefix(value: string, prefixes: readonly string[]): string | null {
  for (const prefix of prefixes) {
    if (!prefix) continue;
    if (prefix.endsWith("-")) {
      if (value.startsWith(prefix) && value.length > prefix.length) {
        return value.slice(prefix.length);
      }
      continue;
    }
    const token = `${prefix}/`;
    if (value.startsWith(token)) return value.slice(token.length);
  }
  return null;
}

export function pinnedModel(canonical: string | null | undefined, pin: ModelPin | null | undefined): PinnedModel | null {
  if (!canonical || !pin) return null;
  return pin.models[canonical] ?? null;
}

/** Lab id for a unique overlay join. Empty when unmatched — do not invent a letter. */
export function overlayLab(
  overlay: string | null | undefined,
  pin: ModelPin | null | undefined,
): string {
  const text = (overlay || "").trim();
  if (!text || !pin) return "";
  const first = text.split("+").map((part) => part.trim()).filter(Boolean)[0] || text;
  const info = pinnedModel(joinOverlay(first, pin).canonical, pin);
  return info?.lab || "";
}

export function directoryPrice(
  canonical: string | null | undefined,
  overlay: string,
  pin: ModelPin | null | undefined,
): { provider: string; input: number; output: number } | null {
  if (!canonical || !pin) return null;
  const row = pin.prices[canonical];
  if (!row) return null;
  const peeled = peelPrefix(overlay.trim(), pin.prefixes);
  const providerFromOverlay = overlay.includes("/")
    ? overlay.trim().split("/", 1)[0]
    : "";
  for (const key of [providerFromOverlay, peeled?.split("/", 1)[0] ?? ""]) {
    const hit = key ? row[key] : undefined;
    if (hit) return { provider: key, input: hit.input, output: hit.output };
  }
  const lab = pin.models[canonical]?.lab;
  if (lab && row[lab]) return { provider: lab, input: row[lab].input, output: row[lab].output };
  const first = Object.entries(row)[0];
  if (!first) return null;
  return { provider: first[0], input: first[1].input, output: first[1].output };
}
