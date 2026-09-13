export type ModelPrice = {
  input: number;
  output: number;
};

export type ModelModalities = {
  input: string[];
  output: string[];
};

export type ReasoningOption = {
  type: string;
  values?: string[];
};

export type PinnedModel = {
  name: string;
  description: string;
  family: string;
  lab: string;
  release_date: string;
  last_updated?: string;
  knowledge?: string;
  context: number | null;
  output: number | null;
  input_limit?: number | null;
  open_weights: boolean;
  reasoning: boolean;
  tool_call: boolean;
  attachment: boolean;
  temperature?: boolean;
  /** Present only when models.dev declared it. */
  structured_output?: boolean;
  /** models.dev input/output enums: text | image | audio | video | pdf */
  modalities: ModelModalities;
  /** Hugging Face URL only; omit display when null. */
  weights: string | null;
  reasoning_options?: ReasoningOption[];
};

export type PinnedLab = {
  name: string;
  /** Pin SVG filename, or empty when BrandMark / letter mark owns the glyph. */
  logo: string;
  /** How LabMark plates a pin SVG. Omitted when logo is empty. */
  tone?: "ink" | "color" | "paper";
};

export type ModelPin = {
  format: string;
  source: string;
  pinned_at: string;
  labs: Record<string, PinnedLab>;
  models: Record<string, PinnedModel>;
  prefixes: string[];
  lookup: Record<string, string[]>;
  prices: Record<string, Record<string, ModelPrice>>;
  aliases: Record<string, string>;
};

export type ModelJoin = {
  overlay: string;
  canonical: string | null;
  hits: string[];
};
