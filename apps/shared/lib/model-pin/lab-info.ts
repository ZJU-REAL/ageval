/**
 * Hand-maintained lab blurbs and official sites. models.dev has no
 * provider description, and its `doc` field is API docs, not the lab
 * homepage. Partial by design: labs without an entry render bare, and
 * new pin labs may appear before this map learns them.
 */
export type LabInfo = {
  description: string;
  website: string;
};

export const LAB_INFO: Record<string, LabInfo> = {
  aisingapore: {
    description: "AI Singapore's national SEA language model programme",
    website: "https://aisingapore.org",
  },
  alibaba: {
    description: "Qwen models from Alibaba",
    website: "https://qwen.ai",
  },
  anthropic: {
    description: "Claude models from Anthropic",
    website: "https://www.anthropic.com",
  },
  "arcee-ai": {
    description: "Small, specialized language models",
    website: "https://www.arcee.ai",
  },
  "bytedance-seed": {
    description: "Doubao and Seed research from ByteDance",
    website: "https://seed.bytedance.com",
  },
  cohere: {
    description: "Enterprise models for search, retrieval, and agents",
    website: "https://cohere.com",
  },
  deepseek: {
    description: "Open reasoning models from DeepSeek",
    website: "https://www.deepseek.com",
  },
  google: {
    description: "Gemini models from Google DeepMind",
    website: "https://deepmind.google",
  },
  ibm: {
    description: "Granite enterprise models from IBM",
    website: "https://www.ibm.com/granite",
  },
  inclusionai: {
    description: "Ling and Ring open models from Ant Group",
    website: "https://github.com/inclusionAI",
  },
  meituan: {
    description: "LongCat models from Meituan",
    website: "https://longcat.ai",
  },
  meta: {
    description: "Llama open models from Meta",
    website: "https://www.llama.com",
  },
  microsoft: {
    description: "Phi and MAI models from Microsoft",
    website: "https://microsoft.ai",
  },
  minimax: {
    description: "Foundation models from MiniMax",
    website: "https://www.minimax.io",
  },
  mistral: {
    description: "Open and commercial models from Mistral AI",
    website: "https://mistral.ai",
  },
  moonshotai: {
    description: "Kimi models from Moonshot AI",
    website: "https://moonshot.ai",
  },
  nvidia: {
    description: "Nemotron models from NVIDIA",
    website: "https://build.nvidia.com",
  },
  openai: {
    description: "GPT models from OpenAI",
    website: "https://openai.com",
  },
  perplexity: {
    description: "Sonar search models from Perplexity",
    website: "https://www.perplexity.ai",
  },
  poolside: {
    description: "Code generation models from Poolside",
    website: "https://poolside.ai",
  },
  sakana: {
    description: "Evolutionary model research from Sakana AI",
    website: "https://sakana.ai",
  },
  sarvam: {
    description: "Indic language models from Sarvam AI",
    website: "https://www.sarvam.ai",
  },
  sdaia: {
    description: "ALLaM Arabic models from SDAIA",
    website: "https://sdaia.gov.sa",
  },
  stepfun: {
    description: "Step models from StepFun",
    website: "https://www.stepfun.com",
  },
  "swiss-ai": {
    description: "Apertus open models from the Swiss AI Initiative",
    website: "https://www.swiss-ai.org",
  },
  tencent: {
    description: "Hunyuan models from Tencent",
    website: "https://hunyuan.tencent.com",
  },
  thinkingmachines: {
    description: "Research from Thinking Machines Lab",
    website: "https://thinkingmachines.ai",
  },
  trendyol: {
    description: "Turkish language models from Trendyol",
    website: "https://www.trendyol.com",
  },
  upstage: {
    description: "Solar models from Upstage",
    website: "https://www.upstage.ai",
  },
  xai: {
    description: "Grok models from xAI",
    website: "https://x.ai",
  },
  xiaomi: {
    description: "MiMo models from Xiaomi",
    website: "https://platform.xiaomimimo.com",
  },
  zhipuai: {
    description: "GLM models from Z.ai",
    website: "https://z.ai",
  },
};
