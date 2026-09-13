/** Shared liquid-gooey knobs for Hub chrome. Fill is per-surface. */

export const LIQUID_BLUR = 3;
export const LIQUID_CONTRAST = 22;
export const LIQUID_SHADOW = "var(--viewer-shadow-pop)";
/** CSS + SVG blob radius for group items / thumbs. Keep hover in sync. */
export const LIQUID_ITEM_RADIUS = 8;

export const LIQUID_MOVE = {
  springiness: 0.84,
  trail: 0.22,
  wobble: 0.1,
  stretch: 0.16,
} as const;

export const liquidGroup = {
  blur: LIQUID_BLUR,
  contrast: LIQUID_CONTRAST,
  shadow: LIQUID_SHADOW,
} as const;
