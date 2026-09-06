export {
  BRAND_MARKS,
  BRAND_MARK_IDS,
  BRAND_MARK_BY_ID,
  FIRST_PARTY_MARK_ID,
  type BrandMarkEntry,
  type BrandMarkTone,
} from "@/lib/brand-marks/catalog";
export { catalogAssetUrl } from "@/lib/brand-marks/assets";
export { githubAvatarUrl, parseGithubLogin } from "@/lib/brand-marks/github";
export {
  resolveEntityMark,
  resolveMechanismMark,
  type EntityMarkHint,
  type ResolvedMark,
} from "@/lib/brand-marks/resolve";
export {
  entityHintFromPackage,
  markFromGithubRepoLink,
  markFromPackage,
} from "@/lib/brand-marks/from-package";
