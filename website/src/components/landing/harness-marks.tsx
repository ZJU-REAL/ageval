import type { SVGProps } from "react";
import { assetPath } from "@/lib/shared";
import { DSH_WHALE_PATH } from "./dsh-whale";

/**
 * Marks for the hero rotate line: coding-agent harnesses plus
 * environments (the two things a plugin can swap).
 *
 * `src` entries render brand SVGs from the shared set with the Hub
 * brand-marks catalog (`apps/shared/lib/brand-marks/assets/`), all
 * pinned to their bare display fill (white or brand color) because
 * `<img>` cannot inherit page color. DSH has no catalog asset yet, so
 * it inlines the landing whale path as currentColor. e2b is the e
 * glyph from the official wordmark SVG; Daytona is the official
 * favicon mark.
 */

export type MarkProps = SVGProps<SVGSVGElement>;

type CatalogMark = {
  id: string;
  name: string;
  src: string;
};

type InlineMark = {
  id: string;
  name: string;
  Mark: (props: MarkProps) => React.ReactElement;
};

export type Harness = CatalogMark | InlineMark;

export function DshMark(props: MarkProps) {
  return (
    <svg viewBox="0 0 512 509.64" aria-hidden="true" {...props}>
      <path fill="currentColor" fillRule="nonzero" d={DSH_WHALE_PATH} />
    </svg>
  );
}

export const HARNESSES: readonly Harness[] = [
  { id: "claude-code", name: "Claude Code", src: assetPath("/images/harness/claude-code.svg") },
  { id: "codex", name: "Codex", src: assetPath("/images/harness/codex.svg") },
  { id: "pi", name: "Pi", src: assetPath("/images/harness/pi.svg") },
  { id: "opencode", name: "OpenCode", src: assetPath("/images/harness/opencode.svg") },
  { id: "dsh", name: "DSH", Mark: DshMark },
  { id: "nooa", name: "NOOA", src: assetPath("/images/harness/nooa.svg") },
  { id: "miniswe", name: "mini-SWE-agent", src: assetPath("/images/harness/miniswe.svg") },
];

/** Environments a plugin can swap; same marquee row as the harnesses. */
export const ENVIRONMENTS: readonly Harness[] = [
  { id: "e2b", name: "E2B", src: assetPath("/images/harness/e2b.svg") },
  { id: "daytona", name: "Daytona", src: assetPath("/images/harness/daytona.svg") },
  { id: "docker", name: "Docker", src: assetPath("/images/harness/docker.svg") },
];
