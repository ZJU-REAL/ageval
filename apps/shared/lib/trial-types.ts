/** Trial / trajectory shapes aligned with local viewer (apps/viewer). */

import type { PhaseTimingDocument, TerminalUsage } from "./evidence.gen";

export type TrialActor = {
  role: string;
  agent: string;
  model?: string | null;
  reasoning_effort?: string | null;
  profile_id?: string;
  invokes?: number;
  latency_ms_sum?: number | null;
  time_label?: string | null;
  usage?: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    total_tokens?: number | null;
    cached_read_tokens?: number | null;
    cache_hit_rate?: number | null;
    cost_amount?: number | null;
    cost_currency?: string | null;
    context_used?: number | null;
    context_size?: number | null;
    label?: string | null;
  } | null;
  usage_label?: string | null;
};

export type Trial = {
  trial_id: string;
  task_id: string;
  status?: string | null;
  reward?: number | null;
  score?: number | null;
  duration?: string | null;
  started?: string | null;
  error?: string | { phase?: string | null; title?: string; message?: string } | null;
  /** Run-phase limits key that was reached, or null. */
  limit?: string | null;
  run_id?: string | null;
  exit_code?: number | null;
  has_evidence?: boolean;
  available_tabs?: string[];
  evidence_relpath?: string | null;
  agent_invocations?: number | null;
  harness_kind?: string | null;
  framework?: string | null;
  /** Box kind: local | docker | e2b | ssh */
  environment?: string | null;
  actors?: TrialActor[];
  agent_label?: string | null;
  model_label?: string | null;
  executor_kind?: string | null;
  provenance?: Record<string, unknown> | null;
  /** Child-only fork provenance. Absent when this Attempt is not a fork. */
  fork?: {
    parent_attempt_id: string;
    checkpoint_seq?: number | null;
    source_model?: string;
    continuation_model?: string;
  } | null;
  /** Child-only replay provenance. Absent when this Attempt is not a replay. */
  replay?: {
    parent_attempt_id: string;
    status?: string | null;
    field?: string | null;
    ordinal?: number | null;
    artifact_id?: string | null;
    first_divergence?: {
      field?: string | null;
      ordinal?: number | null;
      artifact_id?: string | null;
    } | null;
  } | null;
  upstream_url?: string | null;
  upstream_name?: string | null;
  upstream_ref?: string | null;
  note?: string | null;
  dataset_id?: string | null;
  dataset_version?: string | null;
  dataset_ref?: string | null;
  /** Attempt-grain observational bag from summary.extra; omit when empty. */
  extra?: Record<string, unknown> | null;
  /** Wall-time phases (environment/run/evaluate/record/cleanup). Wire shape is generated. */
  phase_timing?: PhaseTimingDocument | null;
  token_timing?: {
    schema?: string;
    segments?: Array<{ id: string; label?: string; tokens?: number }>;
    total_tokens?: number;
  } | null;
  /** Present on a trial detail when analysis/<analyzer>/report.json exists. */
  analysis?: Array<{
    analyzer: string;
    report: Record<string, unknown> | null;
    note: string | null;
  }> | null;
};

export type TreeEntry = {
  path: string;
  name: string;
  type: "file" | "dir";
  size?: number | null;
  profile_id?: string | null;
  invocation?: string | null;
};

export type TrajectoryStep = {
  type?: string;
  role?: string | null;
  part?: string | null;
  content?: string | null;
  turn_index?: number | null;
  session_id?: string | null;
  source?: string | null;
  stop_reason?: string | null;
  ok?: boolean | null;
  error?: string | null;
  invocation?: string;
  invocation_id?: string;
  profile_id?: string | null;
  model?: string | null;
  line?: number;
  /** Sealed terminal usage, plus legacy keys a reader may still see. */
  usage?: (TerminalUsage & Record<string, unknown>) | null;
  extra?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  title?: string | null;
  function_name?: string | null;
  kind?: string | null;
  status?: string | null;
  args?: Record<string, unknown> | unknown[] | string | null;
  raw_output?: Record<string, unknown> | unknown[] | string | null;
  /** Observational tool duration; omit when the sealed step has none. */
  elapsed_ms?: number | null;
  started_at?: string | null;
  /** Copied from the parent display trajectory. The fork cut is after these steps. */
  inherited?: boolean | null;
  ended_at?: string | null;
  outcome?: string | null;
  option_id?: string | null;
  policy?: string | null;
};
