import { agentPackageHref } from "@/lib/agent-models";
import { encodeDatasetId } from "@/lib/api";
import { harnessBrandId } from "@/lib/brand-marks/harness";
import { joinOverlay, loadModelPin } from "@/lib/model-pin";

/**
 * In-app navigation (models tab Model cell): ink at rest, underline +
 * link-deep on hover. Do not paint IKB on the resting text — that floods tables.
 */
export const INTERNAL_LINK_CLASS =
  "text-ink hover:text-link-deep hover:underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

/** Off-site: IKB at rest. */
export const EXTERNAL_LINK_CLASS =
  "text-link hover:text-link-deep hover:underline underline-offset-2";

function firstSegment(raw: string): string {
  return raw.split("+").map((part) => part.trim()).filter(Boolean)[0] || raw.trim();
}

/** `/agents/{id}` for a builtin short id or `org/name` package id. */
export function harnessHref(raw: string | null | undefined): string | undefined {
  const text = (raw || "").trim();
  if (!text) return undefined;
  const first = firstSegment(text);
  if (first.includes("/")) {
    const id = first.replace(/@[^/]+$/, "").trim();
    return id ? agentPackageHref(id) : undefined;
  }
  const id = (first.split("@")[0] || "").trim();
  if (!id || !harnessBrandId(id)) return undefined;
  return agentPackageHref(id.toLowerCase());
}

/** `/models/{canonical}` when overlay uniquely joins the pin. */
export function modelCatalogHref(
  overlay: string | null | undefined,
): string | undefined {
  const text = (overlay || "").trim();
  if (!text) return undefined;
  const canonical = joinOverlay(firstSegment(text), loadModelPin()).canonical;
  if (!canonical) return undefined;
  return `/models/${encodeDatasetId(canonical)}`;
}
