/** Closed Hub catalog. Keys must match services/registry/brand_marks.json.
 *
 * Product marks: official kit / Lobe static SVG / Simple Icons path + official hex.
 * tone: color = as-is; ink = black mark on a fixed white plate;
 * paper = white-heavy mark on a fixed black plate. Plates do not follow theme.
 */

export type BrandMarkTone = "color" | "ink" | "paper";

export type BrandMarkEntry = {
  id: string;
  label: string;
  file: string;
  tone: BrandMarkTone;
};

export const BRAND_MARKS: readonly BrandMarkEntry[] = [
  { id: "anthropic", label: "Anthropic", file: "anthropic.svg", tone: "ink" },
  { id: "arcee-ai", label: "Arcee AI", file: "arcee-ai.svg", tone: "color" },
  { id: "bytedance-seed", label: "ByteDance Seed", file: "bytedance-seed.svg", tone: "color" },
  { id: "claude", label: "Claude", file: "claude.svg", tone: "color" },
  { id: "claude-code", label: "Claude Code", file: "claude-code.svg", tone: "color" },
  { id: "codex", label: "Codex", file: "codex.svg", tone: "color" },
  { id: "cohere", label: "Cohere", file: "cohere.svg", tone: "color" },
  { id: "deepseek", label: "DeepSeek", file: "deepseek.svg", tone: "color" },
  { id: "docker", label: "Docker", file: "docker.svg", tone: "color" },
  { id: "gemini", label: "Gemini", file: "gemini.svg", tone: "color" },
  { id: "github", label: "GitHub", file: "github.svg", tone: "ink" },
  { id: "grok", label: "Grok", file: "grok.svg", tone: "ink" },
  { id: "ibm", label: "IBM", file: "ibm.svg", tone: "color" },
  { id: "kimi", label: "Kimi", file: "kimi.svg", tone: "paper" },
  { id: "meituan", label: "Meituan", file: "meituan.svg", tone: "color" },
  { id: "meta", label: "Meta", file: "meta.svg", tone: "color" },
  { id: "microsoft", label: "Microsoft", file: "microsoft.svg", tone: "color" },
  { id: "minimax", label: "MiniMax", file: "minimax.svg", tone: "color" },
  { id: "miniswe", label: "mini-SWE-agent", file: "miniswe.svg", tone: "color" },
  { id: "mistral", label: "Mistral", file: "mistral.svg", tone: "color" },
  { id: "nvidia", label: "NVIDIA", file: "nvidia.svg", tone: "color" },
  { id: "openai", label: "OpenAI", file: "openai.svg", tone: "ink" },
  { id: "opencode", label: "OpenCode", file: "opencode.svg", tone: "ink" },
  { id: "perplexity", label: "Perplexity", file: "perplexity.svg", tone: "color" },
  { id: "pi", label: "Pi", file: "pi.svg", tone: "ink" },
  { id: "poolside", label: "Poolside", file: "poolside.svg", tone: "color" },
  { id: "qwen", label: "Qwen", file: "qwen.svg", tone: "color" },
  { id: "stepfun", label: "StepFun", file: "stepfun.svg", tone: "color" },
  { id: "tencent", label: "Tencent", file: "tencent.svg", tone: "color" },
  { id: "upstage", label: "Upstage", file: "upstage.svg", tone: "color" },
  { id: "xiaomi", label: "Xiaomi", file: "xiaomi.svg", tone: "color" },
  { id: "zhipu", label: "GLM", file: "zhipu.svg", tone: "color" },
  { id: "zju-real", label: "REAL Lab", file: "zju-real.svg", tone: "color" },
];

/** Bundled first-party mark (ZJU-REAL / ageval). No GitHub avatar fetch. */
export const FIRST_PARTY_MARK_ID = "zju-real";

export const BRAND_MARK_IDS: ReadonlySet<string> = new Set(
  BRAND_MARKS.map((row) => row.id),
);

export const BRAND_MARK_BY_ID = new Map(BRAND_MARKS.map((row) => [row.id, row]));
