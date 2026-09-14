import type { ModelModalities, PinnedModel } from "./types";

export const MODALITY_TABS = [
  "all",
  "text",
  "image",
  "video",
  "pdf",
  "transcription",
  "speech",
] as const;

export type ModalityTab = (typeof MODALITY_TABS)[number];
export type ModalityKind = Exclude<ModalityTab, "all">;

const TEXT_ONLY: ModelModalities = { input: ["text"], output: ["text"] };

export function modelModalities(info?: PinnedModel | null): ModelModalities {
  const raw = info?.modalities;
  if (!raw || typeof raw !== "object") return TEXT_ONLY;
  const input = Array.isArray(raw.input) ? raw.input.filter((x) => typeof x === "string") : [];
  const output = Array.isArray(raw.output) ? raw.output.filter((x) => typeof x === "string") : [];
  if (input.length === 0 && output.length === 0) return TEXT_ONLY;
  return { input, output };
}

export function matchesModalityTab(mods: ModelModalities, tab: ModalityTab): boolean {
  if (tab === "all") return true;
  if (tab === "text") return mods.input.includes("text") || mods.output.includes("text");
  if (tab === "image") return mods.input.includes("image") || mods.output.includes("image");
  if (tab === "video") return mods.input.includes("video") || mods.output.includes("video");
  if (tab === "pdf") return mods.input.includes("pdf") || mods.output.includes("pdf");
  if (tab === "transcription") return mods.input.includes("audio");
  if (tab === "speech") return mods.output.includes("audio");
  return false;
}

/**
 * Row badges. Extra modalities stack (image / video / pdf / transcription / speech).
 * The text badge only appears when the model has no other listed modality.
 */
export function modalityBadges(mods: ModelModalities): ModalityKind[] {
  const badges: ModalityKind[] = [];
  if (mods.input.includes("image") || mods.output.includes("image")) badges.push("image");
  if (mods.input.includes("video") || mods.output.includes("video")) badges.push("video");
  if (mods.input.includes("pdf") || mods.output.includes("pdf")) badges.push("pdf");
  if (mods.input.includes("audio")) badges.push("transcription");
  if (mods.output.includes("audio")) badges.push("speech");
  if (badges.length === 0 && (mods.input.includes("text") || mods.output.includes("text"))) {
    badges.push("text");
  }
  return badges;
}

export function modalityTabFromSearch(raw: string | null): ModalityTab {
  const value = (raw || "").trim().toLowerCase();
  return (MODALITY_TABS as readonly string[]).includes(value) ? (value as ModalityTab) : "all";
}

export function formatModalities(mods: ModelModalities): string {
  const inn = mods.input.length ? mods.input.join(" + ") : "—";
  const out = mods.output.length ? mods.output.join(" + ") : "—";
  return `${inn} → ${out}`;
}
