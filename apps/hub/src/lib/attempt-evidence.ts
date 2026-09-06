/**
 * Client-side projection of uploaded Attempt archives into viewer trial shapes.
 * Mirrors `ageval.viewer.trials` tab / tree / trajectory rules (read-only).
 */

import type {
  Trial,
  TrialActor,
  TrajectoryStep,
  TreeEntry,
} from "@/lib/trial-types";
import { datasetRef, displayAgentName, reasoningEffortFromBinding } from "@/lib/utils";

import {
  FIRST_TAB_ORDER,
  normalizeTabId,
  TAB_ORDER,
  TREE_SCOPES,
  type TabId,
} from "@/components/trial/tabs";
import { environmentFromOverlay, type JobOverlay } from "@/lib/api";

const MAX_TRAJECTORY_STEPS = 2_000;
const MAX_JSONL_LINE = 64_000;

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Sibling extra, else already-sealed usage.extra on old jsonl. Empty omitted. */
export function terminalExtra(
  rec: Record<string, unknown>,
): Record<string, unknown> | null {
  const sibling = asObject(rec.extra);
  if (sibling && Object.keys(sibling).length) return sibling;
  const usage = asObject(rec.usage);
  const nested = usage ? asObject(usage.extra) : null;
  if (nested && Object.keys(nested).length) return nested;
  return null;
}

function observationalBag(value: unknown): Record<string, unknown> | null {
  const bag = asObject(value);
  return bag && Object.keys(bag).length ? bag : null;
}

export function runRootPrefix(runId: string): string {
  return `.ageval/runs/${runId}`;
}

/** Map archive path → path relative to run root (or null if outside). */
export function toRelPath(archivePath: string, runId: string): string | null {
  const prefix = `${runRootPrefix(runId)}/`;
  const root = runRootPrefix(runId);
  if (archivePath === root) return "";
  if (archivePath.startsWith(prefix)) return archivePath.slice(prefix.length);
  return null;
}

/** Started / duration from an Attempt ``summary.json`` (same source as job detail). */
export function clockFromSummaryJson(text: string): {
  started: string | null;
  duration: string | null;
} {
  try {
    const data = JSON.parse(text) as {
      phase_timing?: Trial["phase_timing"] | { started_at?: unknown };
    };
    const raw = data.phase_timing;
    const phase =
      raw && typeof raw === "object"
        ? (raw as Trial["phase_timing"])
        : null;
    const started =
      phase && typeof phase.started_at === "string" && phase.started_at.trim()
        ? phase.started_at.trim()
        : null;
    return { started, duration: durationFromPhaseTiming(phase) };
  } catch {
    return { started: null, duration: null };
  }
}

export function toArchivePath(relPath: string, runId: string): string {
  const clean = relPath.replace(/^\/+/, "");
  return clean ? `${runRootPrefix(runId)}/${clean}` : runRootPrefix(runId);
}

export function fileName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function hasAnyUnder(relPaths: string[], dir: string): boolean {
  const d = dir.replace(/\/$/, "");
  return relPaths.some((p) => p === d || p.startsWith(d + "/"));
}

export const OBSERVATION_REL = "evaluation/observation.jsonl";

/** Attempt-root record-phase file, then any per-invocation copies. */
export function trajectoryRelPaths(relFiles: string[]): string[] {
  if (relFiles.includes("trajectory.jsonl")) return ["trajectory.jsonl"];
  return relFiles
    .filter(
      (p) =>
        p.startsWith("agent/invocations/") && p.endsWith("/trajectory.jsonl"),
    )
    .sort();
}

/** Same rules as `ageval.viewer.trials.surface._available_tabs`. */
export function availableTabsFromPaths(relFiles: string[]): TabId[] {
  const tabs: string[] = [];
  if (trajectoryRelPaths(relFiles).length) tabs.push("trajectory");
  if (hasAnyUnder(relFiles, "agent")) tabs.push("agent");
  if (
    hasAnyUnder(relFiles, "evaluation") ||
    hasAnyUnder(relFiles, "eval_staging") ||
    relFiles.includes("result.json")
  ) {
    tabs.push("verifier");
  }
  if (
    hasAnyUnder(relFiles, "harness") ||
    hasAnyUnder(relFiles, "artifacts") ||
    hasAnyUnder(relFiles, "agent/artifacts")
  ) {
    tabs.push("artifacts");
  }
  if (relFiles.includes("lock.json")) tabs.push("lock");
  if (
    relFiles.includes("effects.jsonl") ||
    relFiles.includes("cleanup.json") ||
    relFiles.includes("summary.json") ||
    relFiles.includes("agent.json") ||
    relFiles.includes("harness.json")
  ) {
    tabs.push("runtime");
  }
  const normalized = tabs.map(normalizeTabId);
  return TAB_ORDER.filter((t) => normalized.includes(t));
}

export function firstTab(tabs: TabId[]): TabId | null {
  return FIRST_TAB_ORDER.find((t) => tabs.includes(t)) || tabs[0] || null;
}

export function treeEntriesForScope(
  relFiles: Array<{ path: string; size?: number }>,
  scope: string,
  invProfileByDir?: Map<string, string | null>,
): { entries: TreeEntry[]; groups: Array<{ key: string; profile_id?: string | null; label?: string }> | null } {
  const scopeNorm = (scope || "root").toLowerCase();
  const asEntry = (rel: string, size?: number, extra?: Partial<TreeEntry>): TreeEntry => ({
    path: rel,
    name: fileName(rel),
    type: "file",
    size: size ?? null,
    ...extra,
  });

  if (scopeNorm === "lock") {
    const hit = relFiles.find((f) => f.path === "lock.json");
    return {
      entries: hit ? [asEntry(hit.path, hit.size)] : [],
      groups: null,
    };
  }

  if (scopeNorm === "runtime" || scopeNorm === "log") {
    const names = [
      "effects.jsonl",
      "cleanup.json",
      "summary.json",
      "agent.json",
      "harness.json",
    ];
    return {
      entries: names
        .map((n) => relFiles.find((f) => f.path === n))
        .filter((f): f is { path: string; size?: number } => !!f)
        .map((f) => asEntry(f.path, f.size)),
      groups: null,
    };
  }

  if (scopeNorm === "verifier" || scopeNorm === "eval" || scopeNorm === "evaluation") {
    const entries: TreeEntry[] = [];
    for (const f of relFiles) {
      if (
        f.path === "result.json" ||
        f.path.startsWith("evaluation/") ||
        f.path.startsWith("eval_staging/")
      ) {
        entries.push(asEntry(f.path, f.size));
      }
    }
    return { entries, groups: null };
  }

  if (scopeNorm === "artifacts") {
    const entries: TreeEntry[] = [];
    for (const f of relFiles) {
      if (
        f.path.startsWith("artifacts/") ||
        f.path.startsWith("harness/") ||
        f.path.startsWith("agent/artifacts/")
      ) {
        entries.push(asEntry(f.path, f.size));
      }
    }
    return { entries, groups: null };
  }

  if (scopeNorm === "agent") {
    const entries: TreeEntry[] = [];
    const profileKeys = new Set<string>();
    for (const f of relFiles) {
      if (!f.path.startsWith("agent/")) continue;
      let profile_id: string | null = null;
      let invocation: string | null = null;
      const m = f.path.match(/^agent\/invocations\/([^/]+)\//);
      if (m) {
        invocation = m[1];
        profile_id = invProfileByDir?.get(m[1]) ?? null;
        if (profile_id) profileKeys.add(profile_id);
      }
      entries.push(asEntry(f.path, f.size, { profile_id, invocation }));
    }
    const groups =
      profileKeys.size >= 2
        ? [...profileKeys].map((k) => ({
            key: k,
            profile_id: k,
            label: k,
          }))
        : null;
    return { entries, groups };
  }

  // root / unknown
  return {
    entries: relFiles.map((f) => asEntry(f.path, f.size)),
    groups: null,
  };
}

export function scopeForTab(tab: TabId): string | null {
  return TREE_SCOPES[tab] ?? null;
}

function projectedAcpEntry(profile: unknown): string {
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return "";
  const rec = profile as Record<string, unknown>;
  if (typeof rec.entry === "string" && rec.entry.trim()) return rec.entry.trim();
  const opts = rec.options;
  if (opts && typeof opts === "object" && !Array.isArray(opts)) {
    const val = (opts as Record<string, unknown>).entry;
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return "";
}

function displayBinding(
  profile: Record<string, unknown>,
  overlay: unknown,
): Record<string, unknown> {
  const src =
    overlay && typeof overlay === "object" && !Array.isArray(overlay)
      ? (overlay as Record<string, unknown>)
      : profile;
  const entry = projectedAcpEntry(src) || projectedAcpEntry(profile);
  if (!entry || src.entry === entry) return src;
  return { ...src, entry };
}

/** Same axis as Jobs: label → ACP entry → executor. Never show transport ``acp``. */
function actorAgentName(
  profile: Record<string, unknown>,
  overlay: unknown,
  invEntry: string | undefined,
): string {
  const name = displayAgentName(displayBinding(profile, overlay));
  if (name && name !== "acp") return name;
  if (invEntry && invEntry.trim()) return invEntry.trim();
  const pid = profile.id;
  if (typeof pid === "string" && pid.trim()) return pid.trim();
  return "";
}

function environmentKind(
  lock: Record<string, unknown>,
  result: Record<string, unknown>,
): string | null {
  for (const raw of [lock.environment, result.kind]) {
    if (typeof raw === "string" && raw.trim()) return raw.trim();
  }
  return environmentFromOverlay(lock.job_overlay as JobOverlay | undefined);
}

export function durationFromPhaseTiming(phaseTiming: Trial["phase_timing"]): string | null {
  if (!phaseTiming || typeof phaseTiming.total_ms !== "number") return null;
  const ms = phaseTiming.total_ms;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalS = ms / 1000;
  if (totalS < 60) {
    if (totalS < 10) return `${totalS.toFixed(1)}s`;
    return `${Math.round(totalS)}s`;
  }
  const minutes = Math.floor(totalS / 60);
  const seconds = Math.round(totalS - minutes * 60);
  if (seconds === 60) return `${minutes + 1}m`;
  return seconds ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${minutes}m`;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function asInt(value: unknown): number | null {
  const n = asFiniteNumber(value);
  if (n == null || !Number.isInteger(n)) return null;
  return n;
}

function fmtTokenCount(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000;
    return v === Math.trunc(v) ? `${v}M` : `${v.toFixed(1)}M`;
  }
  if (n >= 1000) {
    const v = n / 1000;
    return v === Math.trunc(v) ? `${v}K` : `${v.toFixed(1)}K`;
  }
  return String(n);
}

function fmtCost(amount: number): string {
  if (amount === 0) return "0";
  return Number(amount).toPrecision(4).replace(/\.?0+$/, "");
}

export function summarizeUsage(
  usage: Record<string, unknown> | null | undefined,
  extraRaw?: Record<string, unknown> | null,
): NonNullable<TrialActor["usage"]> | null {
  if (!usage && !extraRaw) return null;
  const extra =
    extraRaw && typeof extraRaw === "object" && !Array.isArray(extraRaw)
      ? extraRaw
      : {};
  const fields = usage ?? {};
  const inp =
    asInt(fields.prompt_tokens) ??
    asInt(fields.input_tokens) ??
    asInt(fields.inputTokens);
  const outp =
    asInt(fields.completion_tokens) ??
    asInt(fields.output_tokens) ??
    asInt(fields.outputTokens);
  const cachedRead =
    asInt(fields.cached_tokens) ??
    asInt(fields.cached_read_tokens) ??
    asInt(fields.cachedReadTokens) ??
    asInt(extra.cached_read_tokens);
  const cachedWrite =
    asInt(extra.cached_write_tokens) ??
    asInt(fields.cached_write_tokens) ??
    asInt(fields.cachedWriteTokens);
  const total =
    asInt(extra.total_tokens) ?? asInt(fields.total_tokens) ?? asInt(fields.totalTokens);

  let costAmount = asFiniteNumber(fields.cost_usd);
  let costCurrency: string | null = costAmount != null ? "USD" : null;
  const costRaw =
    extra.cost && typeof extra.cost === "object" && !Array.isArray(extra.cost)
      ? (extra.cost as Record<string, unknown>)
      : fields.cost && typeof fields.cost === "object" && !Array.isArray(fields.cost)
        ? (fields.cost as Record<string, unknown>)
        : null;
  if (costAmount == null && costRaw) {
    costAmount = asFiniteNumber(costRaw.amount);
    if (typeof costRaw.currency === "string" && costRaw.currency.trim()) {
      costCurrency = costRaw.currency.trim();
    }
  }

  const contextRaw =
    extra.context && typeof extra.context === "object" && !Array.isArray(extra.context)
      ? (extra.context as Record<string, unknown>)
      : fields.context && typeof fields.context === "object" && !Array.isArray(fields.context)
        ? (fields.context as Record<string, unknown>)
        : null;
  const contextUsed = asInt(contextRaw?.used) ?? asInt(fields.used);
  const contextSize = asInt(contextRaw?.size) ?? asInt(fields.size);

  let cacheHitRate: number | null = null;
  if (inp != null && cachedRead != null && inp > 0) {
    if (cachedRead <= inp) {
      cacheHitRate = cachedRead / inp;
    } else {
      const denom = inp + cachedRead + (cachedWrite && cachedWrite > 0 ? cachedWrite : 0);
      cacheHitRate = denom > 0 ? cachedRead / denom : null;
    }
  }

  if (
    inp == null &&
    outp == null &&
    costAmount == null &&
    contextUsed == null &&
    contextSize == null
  ) {
    return null;
  }

  const parts: string[] = [];
  if (inp != null || outp != null) {
    parts.push(
      `in ${inp != null ? fmtTokenCount(inp) : "-"} / out ${outp != null ? fmtTokenCount(outp) : "-"}`,
    );
  }
  if (cacheHitRate != null) {
    parts.push(`cache ${Math.round(Math.max(0, Math.min(1, cacheHitRate)) * 100)}%`);
  }
  if (costAmount != null) {
    const cur = (costCurrency || "").toUpperCase();
    parts.push(cur === "" || cur === "USD" ? `$${fmtCost(costAmount)}` : `${fmtCost(costAmount)} ${cur}`);
  }

  return {
    input_tokens: inp,
    output_tokens: outp,
    total_tokens: total,
    cached_read_tokens: cachedRead,
    cache_hit_rate: cacheHitRate,
    cost_amount: costAmount,
    cost_currency: costCurrency,
    context_used: contextUsed,
    context_size: contextSize,
    label: parts.length ? parts.join(" · ") : null,
  };
}

function terminalProfileId(step: TrajectoryStep): string | null {
  if (typeof step.profile_id === "string" && step.profile_id) return step.profile_id;
  const meta = step.metadata;
  if (meta && typeof meta.profile_id === "string" && meta.profile_id) return meta.profile_id;
  return null;
}

function terminalElapsedMs(step: TrajectoryStep): number | null {
  const direct = asFiniteNumber(step.elapsed_ms);
  if (direct != null && direct >= 0) return direct;
  const lat = asFiniteNumber(step.metadata?.latency_ms);
  if (lat != null && lat >= 0) return lat;
  return null;
}

function formatLatencyMs(
  total: number | undefined,
  nInv: number,
): string | null {
  if (total == null || Number.isNaN(total)) return nInv > 0 ? `— (${nInv})` : null;
  const sec = total / 1000;
  const label =
    sec >= 10 ? `${Math.round(sec)}s` : sec >= 1 ? `${sec.toFixed(1)}s` : `${Math.round(total)}ms`;
  return nInv > 0 ? `${label} (${nInv})` : label;
}

export function buildTrialMeta(opts: {
  runId: string;
  taskId: string;
  relFiles: string[];
  result: Record<string, unknown>;
  summary: Record<string, unknown>;
  lock: Record<string, unknown>;
  invMetas: Array<{ dirname: string; meta: Record<string, unknown> }>;
  trajectorySteps?: TrajectoryStep[];
}): Trial {
  const { runId, taskId, relFiles, result, summary, lock, invMetas, trajectorySteps } = opts;
  const tabs = availableTabsFromPaths(relFiles);

  let status =
    (typeof result.status === "string" && result.status) ||
    (typeof summary.status === "string" && summary.status) ||
    null;
  if (status) status = status.toUpperCase();

  let score: number | null = null;
  for (const v of [result.score, summary.score]) {
    if (typeof v === "number" && !Number.isNaN(v)) {
      score = v;
      break;
    }
  }

  let error: string | null = null;
  const errRaw = result.error ?? summary.error;
  if (errRaw != null) {
    error =
      typeof errRaw === "string"
        ? errRaw
        : (() => {
            try {
              return JSON.stringify(errRaw);
            } catch {
              return String(errRaw);
            }
          })();
  }

  const profilesRaw = Array.isArray(lock.profiles) ? lock.profiles : [];
  const byId = new Map<string, Record<string, unknown>>();
  for (const p of profilesRaw) {
    if (p && typeof p === "object" && !Array.isArray(p)) {
      const pid = (p as Record<string, unknown>).id;
      if (typeof pid === "string" && pid) byId.set(pid, p as Record<string, unknown>);
    }
  }

  const orderedIds: string[] = [];
  const invModel = new Map<string, string>();
  const invExecutor = new Map<string, string>();
  const invEntry = new Map<string, string>();
  const invEffort = new Map<string, string>();
  const overlayBindings =
    lock.job_overlay &&
    typeof lock.job_overlay === "object" &&
    (lock.job_overlay as Record<string, unknown>).agent_profiles &&
    typeof (lock.job_overlay as Record<string, unknown>).agent_profiles ===
      "object"
      ? ((lock.job_overlay as Record<string, unknown>).agent_profiles as Record<
          string,
          unknown
        >)
      : {};
  const latencySum = new Map<string, number>();
  const invokeCount = new Map<string, number>();

  for (const { dirname, meta } of invMetas) {
    const pid = meta.profile_id;
    if (typeof pid !== "string" || !pid) continue;
    if (!orderedIds.includes(pid)) orderedIds.push(pid);
    const mid = meta.model ?? meta.locked_model;
    if (typeof mid === "string" && mid) invModel.set(pid, mid);
    const ek = meta.executor_kind;
    if (typeof ek === "string" && ek) invExecutor.set(pid, ek);
    const acpEntry = meta.acp_entry_id;
    if (typeof acpEntry === "string" && acpEntry.trim()) {
      invEntry.set(pid, acpEntry.trim());
    }
    const effort =
      (typeof meta.actual_reasoning_effort === "string" &&
        meta.actual_reasoning_effort.trim()) ||
      (typeof meta.locked_reasoning_effort === "string" &&
        meta.locked_reasoning_effort.trim()) ||
      "";
    if (effort) invEffort.set(pid, effort);
    invokeCount.set(pid, (invokeCount.get(pid) || 0) + 1);
    const lat = meta.latency_ms;
    if (typeof lat === "number" && !Number.isNaN(lat)) {
      latencySum.set(pid, (latencySum.get(pid) || 0) + lat);
    }
    void dirname;
  }

  const jsonlUsage = new Map<string, Record<string, unknown>>();
  const jsonlExtra = new Map<string, Record<string, unknown>>();
  const jsonlLatency = new Map<string, number>();
  const jsonlCount = new Map<string, number>();
  for (const step of trajectorySteps || []) {
    if (step.type !== "terminal") continue;
    const pid = terminalProfileId(step);
    if (!pid) continue;
    if (!orderedIds.includes(pid)) orderedIds.push(pid);
    if (step.usage && typeof step.usage === "object") {
      jsonlUsage.set(pid, step.usage);
    }
    if (step.extra && typeof step.extra === "object") {
      jsonlExtra.set(pid, step.extra);
    }
    const elapsed = terminalElapsedMs(step);
    if (elapsed != null) {
      jsonlLatency.set(pid, (jsonlLatency.get(pid) || 0) + elapsed);
      jsonlCount.set(pid, (jsonlCount.get(pid) || 0) + 1);
    }
    const mid = step.model ?? step.metadata?.model ?? step.metadata?.locked_model;
    if (typeof mid === "string" && mid) invModel.set(pid, mid);
    const ek = step.metadata?.executor_kind;
    if (typeof ek === "string" && ek) invExecutor.set(pid, ek);
  }
  if (orderedIds.length === 0) {
    for (const pid of byId.keys()) orderedIds.push(pid);
  }

  const actors: TrialActor[] = [];
  const executors: string[] = [];
  for (const pid of orderedIds) {
    const p = byId.get(pid) || { id: pid };
    let ex = typeof p.executor === "string" ? p.executor : null;
    if (!ex) ex = invExecutor.get(pid) || null;
    if (ex && !executors.includes(ex)) executors.push(ex);
    const model =
      invModel.get(pid) ||
      (typeof p.model === "string" ? p.model : null);
    const overlay = overlayBindings[pid];
    const effort =
      invEffort.get(pid) ||
      reasoningEffortFromBinding(overlay) ||
      reasoningEffortFromBinding(p) ||
      null;
    const agentCol =
      actorAgentName(p, overlay, invEntry.get(pid)) || pid;
    const roleCol = pid;
    const nInv = jsonlCount.get(pid) || invokeCount.get(pid) || 0;
    const latTotal = jsonlLatency.has(pid) ? jsonlLatency.get(pid) : latencySum.get(pid);
    const usageSummary = summarizeUsage(
      jsonlUsage.get(pid) ?? null,
      jsonlExtra.get(pid) ?? null,
    );
    actors.push({
      role: roleCol,
      agent: agentCol,
      model,
      reasoning_effort: effort,
      profile_id: pid,
      invokes: nInv,
      latency_ms_sum: latTotal ?? null,
      time_label: formatLatencyMs(latTotal, nInv),
      usage: usageSummary,
      usage_label: usageSummary?.label ?? null,
    });
  }

  const framework: string | null = executors[0] || null;

  const prov =
    lock.provenance && typeof lock.provenance === "object"
      ? (lock.provenance as Record<string, unknown>)
      : null;
  const upstream =
    prov?.upstream && typeof prov.upstream === "object"
      ? (prov.upstream as Record<string, unknown>)
      : null;

  const phaseTimingRaw =
    summary.phase_timing && typeof summary.phase_timing === "object"
      ? summary.phase_timing
      : null;
  const phase_timing = phaseTimingRaw as Trial["phase_timing"];
  const started =
    phase_timing && typeof phase_timing.started_at === "string"
      ? phase_timing.started_at
      : null;
  const duration = durationFromPhaseTiming(phase_timing);

  // Token bar from actor usage when present (often null on Hub until usage wired).
  let token_timing: Trial["token_timing"] = null;
  {
    let cached = 0;
    let uncached = 0;
    let output = 0;
    let anyTok = false;
    for (const a of actors) {
      const u = a.usage;
      if (!u) continue;
      if (typeof u.output_tokens === "number") {
        output += u.output_tokens;
        anyTok = true;
      }
      if (typeof u.input_tokens === "number") {
        anyTok = true;
        const cr =
          typeof u.cached_read_tokens === "number" ? u.cached_read_tokens : 0;
        cached += cr;
        uncached += Math.max(0, u.input_tokens - cr);
      }
    }
    if (anyTok) {
      token_timing = {
        schema: "ageval.token_timing/1",
        segments: [
          { id: "cached_input", label: "Cached Input", tokens: Math.round(cached) },
          {
            id: "uncached_input",
            label: "Uncached Input",
            tokens: Math.round(uncached),
          },
          { id: "output", label: "Output", tokens: Math.round(output) },
        ],
        total_tokens: Math.round(cached + uncached + output),
      };
    }
  }

  const invCount =
    (typeof result.agent_invocations === "number" && result.agent_invocations) ||
    (typeof summary.agent_invocations === "number" && summary.agent_invocations) ||
    invMetas.length ||
    null;

  return {
    trial_id: runId,
    run_id: runId,
    task_id: taskId,
    status,
    score,
    reward: score,
    error,
    started,
    duration,
    phase_timing,
    token_timing,
    has_evidence: true,
    available_tabs: tabs,
    agent_invocations: invCount,
    harness_kind:
      (typeof result.harness_kind === "string" && result.harness_kind) ||
      (typeof summary.harness_kind === "string" && summary.harness_kind) ||
      null,
    framework,
    environment: environmentKind(lock, result),
    actors,
    agent_label: actors.length === 1 ? actors[0].role : null,
    model_label: actors.length === 1 ? actors[0].model ?? null : null,
    executor_kind: executors[0] || null,
    provenance: prov,
    upstream_url:
      typeof upstream?.url === "string" && upstream.url.trim()
        ? upstream.url
        : null,
    upstream_name:
      typeof upstream?.name === "string" && upstream.name.trim()
        ? upstream.name
        : null,
    upstream_ref:
      typeof upstream?.ref === "string" && upstream.ref.trim()
        ? upstream.ref
        : null,
    note: null,
    extra: observationalBag(summary.extra),
    dataset_id: typeof lock.dataset_id === "string" ? lock.dataset_id : null,
    dataset_version:
      typeof lock.dataset_version === "string" ? lock.dataset_version : null,
    dataset_ref: datasetRef(
      typeof lock.dataset_id === "string" ? lock.dataset_id : null,
      typeof lock.dataset_version === "string" ? lock.dataset_version : null,
    ),
  };
}

/** Copy package-role profile_id onto rows that only the terminal carried. */
export function backfillStepProfileIds(steps: TrajectoryStep[]): TrajectoryStep[] {
  const byTurn = new Map<number, string>();
  for (const step of steps) {
    const ti = step.turn_index;
    if (typeof ti !== "number") continue;
    let pid = typeof step.profile_id === "string" && step.profile_id ? step.profile_id : "";
    if (!pid) {
      const meta = step.metadata;
      const raw = meta && typeof meta.profile_id === "string" ? meta.profile_id : "";
      if (raw) pid = raw;
    }
    if (pid) byTurn.set(ti, pid);
  }
  for (const step of steps) {
    if (typeof step.profile_id === "string" && step.profile_id) continue;
    const ti = step.turn_index;
    const pid = typeof ti === "number" ? byTurn.get(ti) : undefined;
    if (pid) step.profile_id = pid;
  }
  return steps;
}

/** Parse one trajectory.jsonl body into viewer steps. */
export function parseTrajectoryJsonl(text: string): TrajectoryStep[] {
  const steps: TrajectoryStep[] = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (steps.length >= MAX_TRAJECTORY_STEPS) break;
    let raw = lines[i].trim();
    if (!raw) continue;
    if (raw.length > MAX_JSONL_LINE) raw = raw.slice(0, MAX_JSONL_LINE);
    let obj: unknown;
    try {
      obj = JSON.parse(raw);
    } catch {
      steps.push({ type: "parse_error", line: i + 1, content: raw.slice(0, 500) });
      continue;
    }
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
      steps.push({ type: "raw", line: i + 1, content: String(obj).slice(0, 500) });
      continue;
    }
    const rec = obj as Record<string, unknown>;
    const role = rec.role;
    const stepType =
      (typeof rec.type === "string" && rec.type) ||
      (role ? "turn" : "event");
    let content = rec.content;
    if (content != null && typeof content !== "string") {
      try {
        content = JSON.stringify(content);
      } catch {
        content = String(content);
      }
    }
    if (typeof content === "string" && content.length > 8_000) {
      content = content.slice(0, 8_000) + "…[truncated]";
    }
    const args = rec.args;
    const rawOutput = rec.raw_output;
    if (stepType === "tool_call" && content == null && args != null) {
      try {
        content = JSON.stringify(args);
      } catch {
        content = String(args);
      }
      if (typeof content === "string" && content.length > 8_000) {
        content = content.slice(0, 8_000) + "…[truncated]";
      }
    }
    if (stepType === "observation" && content == null && rawOutput != null) {
      try {
        content = JSON.stringify(rawOutput);
      } catch {
        content = String(rawOutput);
      }
      if (typeof content === "string" && content.length > 8_000) {
        content = content.slice(0, 8_000) + "…[truncated]";
      }
    }
    steps.push({
      type: stepType,
      role: typeof role === "string" ? role : null,
      part: typeof rec.part === "string" ? rec.part : null,
      content: typeof content === "string" ? content : null,
      turn_index: typeof rec.turn_index === "number" ? rec.turn_index : null,
      session_id: typeof rec.session_id === "string" ? rec.session_id : null,
      source: typeof rec.source === "string" ? rec.source : null,
      stop_reason: typeof rec.stop_reason === "string" ? rec.stop_reason : null,
      ok: typeof rec.ok === "boolean" ? rec.ok : null,
      error: rec.error != null ? String(rec.error) : null,
      line: i + 1,
      usage:
        rec.usage && typeof rec.usage === "object"
          ? (rec.usage as Record<string, unknown>)
          : null,
      extra: terminalExtra(rec),
      metadata:
        rec.metadata && typeof rec.metadata === "object"
          ? (rec.metadata as Record<string, unknown>)
          : null,
      tool_call_id:
        typeof rec.tool_call_id === "string" ? rec.tool_call_id : null,
      title: typeof rec.title === "string" ? rec.title : null,
      function_name:
        typeof rec.function_name === "string" ? rec.function_name : null,
      kind: typeof rec.kind === "string" ? rec.kind : null,
      status: typeof rec.status === "string" ? rec.status : null,
      args: (args as TrajectoryStep["args"]) ?? null,
      raw_output: (rawOutput as TrajectoryStep["raw_output"]) ?? null,
      elapsed_ms:
        typeof rec.elapsed_ms === "number" && Number.isFinite(rec.elapsed_ms)
          ? rec.elapsed_ms
          : null,
      profile_id:
        typeof rec.profile_id === "string"
          ? rec.profile_id
          : rec.metadata &&
              typeof rec.metadata === "object" &&
              !Array.isArray(rec.metadata) &&
              typeof (rec.metadata as Record<string, unknown>).profile_id ===
                "string"
            ? String((rec.metadata as Record<string, unknown>).profile_id)
            : null,
      started_at: typeof rec.started_at === "string" ? rec.started_at : null,
      ended_at: typeof rec.ended_at === "string" ? rec.ended_at : null,
      outcome: typeof rec.outcome === "string" ? rec.outcome : null,
      option_id: typeof rec.option_id === "string" ? rec.option_id : null,
      policy: typeof rec.policy === "string" ? rec.policy : null,
    });
  }
  return backfillStepProfileIds(steps);
}

export function invDirFromTrajPath(rel: string): string | null {
  const m = rel.match(/^agent\/invocations\/([^/]+)\/trajectory\.jsonl$/);
  return m ? m[1] : null;
}
