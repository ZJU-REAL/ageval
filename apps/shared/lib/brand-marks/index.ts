export {
  BRAND_MARKS,
  BRAND_MARK_IDS,
  BRAND_MARK_BY_ID,
  FIRST_PARTY_MARK_ID,
  type BrandMarkEntry,
  type BrandMarkTone,
} from "@ageval/shared/lib/brand-marks/catalog";
export { catalogAssetUrl } from "@ageval/shared/lib/brand-marks/assets";
export { HARNESS_BRAND_MARK, harnessBrandId } from "@ageval/shared/lib/brand-marks/harness";
export { githubAvatarUrl, parseGithubLogin } from "@ageval/shared/lib/brand-marks/github";
export {
  resolveEntityMark,
  resolveMechanismMark,
  type EntityMarkHint,
  type ResolvedMark,
} from "@ageval/shared/lib/brand-marks/resolve";
export {
  entityHintFromPackage,
  markFromGithubRepoLink,
  markFromPackage,
  type PackageMarkSource,
} from "@ageval/shared/lib/brand-marks/from-package";
