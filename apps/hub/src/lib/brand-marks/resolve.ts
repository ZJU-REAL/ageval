import {
  BRAND_MARK_IDS,
  FIRST_PARTY_MARK_ID,
} from "@/lib/brand-marks/catalog";
import { githubAvatarUrl, parseGithubLogin } from "@/lib/brand-marks/github";

export type ResolvedMark =
  | { kind: "catalog"; id: string }
  | { kind: "github"; login: string; src: string }
  | { kind: "letter"; letter: string };

export type EntityMarkHint = {
  iconKey?: string | null;
  iconGithub?: string | null;
  uploadedBy?: string | null;
  displayName?: string | null;
  packageId?: string | null;
  /** Official-org package: default the bundled first-party mark, not GitHub. */
  official?: boolean | null;
  /** Builtin plugin / agent: same bundled default when no icon_key. */
  builtin?: boolean | null;
};

function firstLetter(raw: string): string {
  const ch = [...raw].find((c) => /[a-z0-9]/i.test(c));
  return (ch || "?").toUpperCase();
}

function leafName(id: string): string {
  const parts = id.split("/").filter(Boolean);
  return parts[parts.length - 1] || id;
}

export function resolveEntityMark(hint: EntityMarkHint): ResolvedMark {
  const key = (hint.iconKey || "").trim().toLowerCase();
  if (key && BRAND_MARK_IDS.has(key)) return { kind: "catalog", id: key };

  const github = parseGithubLogin(hint.iconGithub);
  if (github) {
    return { kind: "github", login: github, src: githubAvatarUrl(github) };
  }

  if (hint.official || hint.builtin) {
    return { kind: "catalog", id: FIRST_PARTY_MARK_ID };
  }

  const uploader = parseGithubLogin(hint.uploadedBy);
  if (uploader) {
    return { kind: "github", login: uploader, src: githubAvatarUrl(uploader) };
  }

  const label =
    (hint.displayName || "").trim() ||
    leafName(hint.packageId || "") ||
    (hint.uploadedBy || "").trim();
  return { kind: "letter", letter: firstLetter(label) };
}

export function resolveMechanismMark(
  raw: string | null | undefined,
): string | null {
  const key = (raw || "").trim().toLowerCase();
  return key && BRAND_MARK_IDS.has(key) ? key : null;
}
