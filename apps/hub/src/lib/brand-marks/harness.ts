import { BRAND_MARK_IDS } from "@/lib/brand-marks/catalog";

/**
 * Builtin harness id → Hub brand-marks catalog id.
 * Keep in lockstep with services/registry/builtin_agents.py HARNESS_ICON_KEY.
 * grok-build / openai-http / anthropic-http reuse the parent brand; they are
 * not a models.dev lab set.
 */
export const HARNESS_BRAND_MARK: Record<string, string> = {
  pi: "pi",
  opencode: "opencode",
  codex: "codex",
  "claude-code": "claude-code",
  "grok-build": "grok",
  "openai-http": "openai",
  "anthropic-http": "anthropic",
};

/** Catalog id for a unique builtin harness. Empty when unmatched — no letter. */
export function harnessBrandId(raw: string | null | undefined): string | null {
  const text = (raw || "").trim();
  if (!text) return null;
  const first =
    text.split("+").map((part) => part.trim()).filter(Boolean)[0] || text;
  if (first.includes("/")) return null;
  const id = (first.split("@")[0] || "").trim().toLowerCase();
  const mark = HARNESS_BRAND_MARK[id];
  return mark && BRAND_MARK_IDS.has(mark) ? mark : null;
}
