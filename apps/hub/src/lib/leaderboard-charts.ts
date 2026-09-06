/**
 * Observational Leaderboard chart helpers (waffle / Pareto).
 * Never suite PASS. Cost from agent usage, else token × pin directory price.
 */
import type { SuiteRow } from "@/lib/api";
import { overlayAgentProfiles } from "@/lib/api";
import {
  directoryPrice,
  joinOverlay,
  type ModelPin,
} from "@/lib/model-pin";

export type BoardChart = "table" | "waffle" | "pareto";
export type ParetoAxis = "cost" | "tokens" | "time";
export type TrialKind = "pass" | "fail" | "error";
export type CostSource = "reported" | "estimated" | "missing";

export const BOARD_CHARTS: readonly { id: BoardChart; label: string }[] = [
  { id: "table", label: "Table" },
  { id: "pareto", label: "Pareto" },
  { id: "waffle", label: "Waffle" },
];

export const PARETO_AXES: readonly { id: ParetoAxis; label: string }[] = [
  { id: "cost", label: "Cost" },
  { id: "tokens", label: "Tokens" },
  { id: "time", label: "Time" },
];

export type WaffleTrial = {
  key: string;
  kind: TrialKind;
  taskId: string;
  runId: string | null;
  hasAttempt: boolean;
  attemptIndex: number;
};

export type SuiteUsage = {
  promptTokens: number | null;
  completionTokens: number | null;
  cachedTokens: number | null;
  costUsd: number | null;
  costUsdEstimated: number | null;
  costSource: CostSource | null;
  durationS: number | null;
};

export type SuiteChartPoint = {
  suite: SuiteRow;
  passRate: number | null;
  tokens: number | null;
  durationS: number | null;
  costUsd: number | null;
  costSource: CostSource;
};

const CHART_IDS = new Set<string>(BOARD_CHARTS.map((c) => c.id));
const AXIS_IDS = new Set<string>(PARETO_AXES.map((c) => c.id));

export function parseBoardChart(raw: string | null | undefined): BoardChart {
  const v = (raw || "").trim().toLowerCase();
  return CHART_IDS.has(v) ? (v as BoardChart) : "table";
}

export function parseParetoAxis(raw: string | null | undefined): ParetoAxis {
  const v = (raw || "").trim().toLowerCase();
  return AXIS_IDS.has(v) ? (v as ParetoAxis) : "cost";
}

export function trialKind(raw: string | null | undefined): TrialKind {
  const s = (raw || "").trim().toUpperCase();
  if (s === "PASS") return "pass";
  if (s === "FAIL") return "fail";
  return "error";
}

function finite(n: unknown): number | null {
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function usageBag(metrics: Record<string, unknown> | null | undefined): Record<string, unknown> {
  const raw = metrics?.usage;
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {};
}

/** Observational usage on suite metrics, when upload/summary carried it. */
export function suiteUsage(suite: SuiteRow): SuiteUsage {
  const m = suite.metrics || {};
  const u = usageBag(m);
  const sourceRaw = u.cost_source;
  const costSource =
    sourceRaw === "reported" || sourceRaw === "estimated" || sourceRaw === "missing"
      ? sourceRaw
      : null;
  return {
    promptTokens: finite(u.prompt_tokens) ?? finite(m.prompt_tokens),
    completionTokens: finite(u.completion_tokens) ?? finite(m.completion_tokens),
    cachedTokens: finite(u.cached_tokens) ?? finite(m.cached_tokens),
    costUsd: finite(u.cost_usd) ?? finite(m.cost_usd),
    costUsdEstimated: finite(u.cost_usd_estimated),
    costSource,
    durationS: finite(u.duration_s) ?? finite(m.duration_s),
  };
}

export function totalTokens(usage: SuiteUsage): number | null {
  const a = usage.promptTokens;
  const b = usage.completionTokens;
  if (a == null && b == null) return null;
  return (a ?? 0) + (b ?? 0);
}

function overlayModel(suite: SuiteRow): string {
  const profiles = overlayAgentProfiles(suite.job_overlay);
  for (const profile of Object.values(profiles)) {
    const model = profile?.model;
    if (typeof model === "string" && model.trim()) return model.trim();
  }
  return (suite.model_label || "").trim();
}

export function estimateCostUsd(
  usage: SuiteUsage,
  suite: SuiteRow,
  pin: ModelPin | null | undefined,
): number | null {
  const prompt = usage.promptTokens;
  const completion = usage.completionTokens;
  if (prompt == null && completion == null) return null;
  const overlay = overlayModel(suite);
  if (!overlay || !pin) return null;
  const joined = joinOverlay(overlay, pin);
  const price = directoryPrice(joined.canonical, overlay, pin);
  if (!price) return null;
  const cached = usage.cachedTokens ?? 0;
  const billedPrompt = Math.max(0, (prompt ?? 0) - cached);
  return (
    (billedPrompt / 1_000_000) * price.input +
    (cached / 1_000_000) * price.input +
    ((completion ?? 0) / 1_000_000) * price.output
  );
}

export function suiteChartPoint(
  suite: SuiteRow,
  pin: ModelPin | null | undefined,
): SuiteChartPoint {
  const usage = suiteUsage(suite);
  const tokens = totalTokens(usage);
  let costUsd: number | null = null;
  let costSource: CostSource = "missing";
  if (usage.costSource === "reported" && usage.costUsd != null) {
    costUsd = usage.costUsd;
    costSource = "reported";
  } else if (usage.costUsdEstimated != null) {
    costUsd = usage.costUsdEstimated;
    costSource = "estimated";
  } else if (usage.costUsd != null) {
    costUsd = usage.costUsd;
    costSource = "reported";
  } else {
    const est = estimateCostUsd(usage, suite, pin);
    if (est != null) {
      costUsd = est;
      costSource = "estimated";
    }
  }
  return {
    suite,
    passRate: finite(suite.pass_rate),
    tokens,
    durationS: usage.durationS,
    costUsd,
    costSource,
  };
}

export function axisValue(point: SuiteChartPoint, axis: ParetoAxis): number | null {
  if (axis === "cost") return point.costUsd;
  if (axis === "tokens") return point.tokens;
  return point.durationS;
}

type TaskRef = NonNullable<SuiteRow["task_refs"]>[number];

function refRunIds(ref: TaskRef): string[] {
  if (Array.isArray(ref.attempt_run_ids) && ref.attempt_run_ids.length) {
    return ref.attempt_run_ids.filter((id): id is string => Boolean(id));
  }
  return ref.run_id ? [ref.run_id] : [];
}

/**
 * One square per attempt. Prefer previous[] + current status.
 * When history is missing, paint c PASS then the rest FAIL (observational).
 */
export function trialsForRef(
  suiteRunId: string,
  ref: TaskRef,
): WaffleTrial[] {
  const taskId = (ref.task_id || "").trim();
  if (!taskId) return [];
  const ids = refRunIds(ref);
  const previous = Array.isArray(ref.previous) ? ref.previous : [];
  const hasAttempt = Boolean(ref.has_attempt_content);
  const out: WaffleTrial[] = [];

  if (previous.length) {
    previous.forEach((row, i) => {
      const runId = typeof row.run_id === "string" ? row.run_id : null;
      out.push({
        key: `${suiteRunId}:${taskId}:prev:${runId || i}`,
        kind: trialKind(row.status),
        taskId,
        runId,
        hasAttempt: Boolean(runId) && hasAttempt,
        attemptIndex: typeof row.attempt_index === "number" ? row.attempt_index : i,
      });
    });
    out.push({
      key: `${suiteRunId}:${taskId}:${ref.run_id || "current"}`,
      kind: trialKind(ref.status),
      taskId,
      runId: ref.run_id ?? null,
      hasAttempt: Boolean(ref.run_id) && hasAttempt,
      attemptIndex: previous.length,
    });
    return out;
  }

  const n =
    typeof ref.n === "number" && Number.isFinite(ref.n) && ref.n >= 1
      ? Math.floor(ref.n)
      : Math.max(1, ids.length);
  const c =
    typeof ref.c === "number" && Number.isFinite(ref.c) && ref.c >= 0
      ? Math.min(n, Math.floor(ref.c))
      : trialKind(ref.status) === "pass"
        ? n
        : 0;
  for (let i = 0; i < n; i++) {
    const runId = ids[i] ?? (i === n - 1 ? ref.run_id ?? null : null);
    let kind: TrialKind = "fail";
    if (i < c) kind = "pass";
    else if (i === n - 1) kind = trialKind(ref.status);
    out.push({
      key: `${suiteRunId}:${taskId}:${runId || i}`,
      kind,
      taskId,
      runId,
      hasAttempt: Boolean(runId) && hasAttempt,
      attemptIndex: i,
    });
  }
  return out;
}

export function waffleTaskIds(suites: SuiteRow[]): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const suite of suites) {
    for (const ref of suite.task_refs || []) {
      const id = (ref.task_id || "").trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      ids.push(id);
    }
  }
  return ids.sort((a, b) => {
    const av = waffleTaskPassCount(suites, a);
    const bv = waffleTaskPassCount(suites, b);
    if (av !== bv) return bv - av;
    return a.localeCompare(b);
  });
}

function waffleTaskPassCount(suites: SuiteRow[], taskId: string): number {
  let n = 0;
  for (const suite of suites) {
    for (const ref of suite.task_refs || []) {
      if ((ref.task_id || "").trim() !== taskId) continue;
      n += trialsForRef(suite.suite_run_id, ref).filter((t) => t.kind === "pass")
        .length;
    }
  }
  return n;
}

export function formatUsd(n: number): string {
  if (n >= 100) return `$${n.toFixed(0)}`;
  if (n >= 10) return `$${n.toFixed(1)}`;
  return `$${n.toFixed(2)}`;
}

export function formatDurationS(n: number): string {
  const s = Math.max(0, Math.round(n));
  const m = Math.floor(s / 60);
  if (m <= 0) return `${s}s`;
  return `${m}m ${s % 60}s`;
}

export function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(Math.round(n));
}
