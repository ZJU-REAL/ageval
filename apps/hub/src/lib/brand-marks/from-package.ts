import type { PackageRelease } from "@/lib/api";
import { FIRST_PARTY_MARK_ID } from "@/lib/brand-marks/catalog";
import { resolveEntityMark, type EntityMarkHint, type ResolvedMark } from "@/lib/brand-marks/resolve";

export function entityHintFromPackage(row: PackageRelease): EntityMarkHint {
  return {
    iconKey: row.icon_key,
    iconGithub: row.icon_github,
    uploadedBy: row.uploaded_by,
    displayName: row.display_name || row.agent_preview?.label || null,
    packageId: row.dataset_id,
    official: row.official,
    builtin: row.builtin,
  };
}

export function markFromPackage(row: PackageRelease) {
  return resolveEntityMark(entityHintFromPackage(row));
}

/** Bundled first-party mark (same identity as the sidebar GitHub link). */
export function markFromGithubRepoLink(): ResolvedMark {
  return { kind: "catalog", id: FIRST_PARTY_MARK_ID };
}
