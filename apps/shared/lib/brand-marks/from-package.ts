import { FIRST_PARTY_MARK_ID } from "@ageval/shared/lib/brand-marks/catalog";
import { resolveEntityMark, type EntityMarkHint, type ResolvedMark } from "@ageval/shared/lib/brand-marks/resolve";

/** Duck type for a Registry package row — Hub passes PackageRelease. */
export type PackageMarkSource = {
  icon_key?: string | null;
  icon_github?: string | null;
  uploaded_by?: string | null;
  display_name?: string | null;
  dataset_id?: string | null;
  official?: boolean | null;
  builtin?: boolean | null;
  agent_preview?: { label?: string | null } | null;
};

export function entityHintFromPackage(row: PackageMarkSource): EntityMarkHint {
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

export function markFromPackage(row: PackageMarkSource) {
  return resolveEntityMark(entityHintFromPackage(row));
}

/** Bundled first-party mark (same identity as the sidebar GitHub link). */
export function markFromGithubRepoLink(): ResolvedMark {
  return { kind: "catalog", id: FIRST_PARTY_MARK_ID };
}
