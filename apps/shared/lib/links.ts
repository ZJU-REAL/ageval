/**
 * In-app navigation (models tab Model cell): ink at rest, underline +
 * link-deep on hover. Do not paint IKB on the resting text — that floods tables.
 */
export const INTERNAL_LINK_CLASS =
  "text-ink hover:text-link-deep hover:underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

/** Off-site: IKB at rest. */
export const EXTERNAL_LINK_CLASS =
  "text-link hover:text-link-deep hover:underline underline-offset-2";
