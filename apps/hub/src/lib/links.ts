import { agentPackageHref } from "@/lib/agent-models";
import { encodeDatasetId } from "@/lib/api";
import { harnessBrandId } from "@ageval/shared/lib/brand-marks/harness";
import { joinOverlay, loadModelPin } from "@ageval/shared/lib/model-pin";

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
