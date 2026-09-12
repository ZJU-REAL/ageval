import {
  BRAND_MARK_BY_ID,
  catalogAssetUrl,
  type BrandMarkTone,
} from "@/lib/brand-marks";
import { LAB_BRAND_MARK, labLogoSrc, loadModelPin, type ModelPin } from "@/lib/model-pin";

/** SVG src + plate tone for a joined lab. Empty when there is no catalog / pin logo. */
export function resolveLabMarkAsset(
  lab: string,
  pin?: ModelPin,
): { src: string; tone: BrandMarkTone } | null {
  const id = lab.trim();
  if (!id) return null;
  const brandId = LAB_BRAND_MARK[id];
  if (brandId) {
    const entry = BRAND_MARK_BY_ID.get(brandId);
    const src = entry ? catalogAssetUrl(entry.file) : undefined;
    if (src && entry) return { src, tone: entry.tone };
  }
  const snapshot = pin ?? loadModelPin();
  const row = snapshot.labs[id];
  if (row?.logo) {
    return { src: labLogoSrc(id), tone: row.tone ?? "color" };
  }
  return null;
}
