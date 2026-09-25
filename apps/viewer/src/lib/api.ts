export type Job = {
  job_id: string;
  job_name: string;
  source: string;
  /** suite = .ageval/suite-runs; single = one-off ageval run Attempt. */
  source_kind?: "suite" | "single" | string;
  dataset_id?: string | null;
  dataset_version?: string | null;
  /** Locked package identity: dataset_id@version from summary or lock. */
  dataset_ref?: string | null;
  agent_label?: string;
  model_label?: string;
  reasoning_effort?: string;
  overlays?: string[];
  provider_label?: string;
  environment?: string;
  result?: number | null;
  pass_rate?: number | null;
  mean_score?: number | null;
  started?: string | null;
  duration?: string | null;
  trials_done?: number;
  trials_total?: number;
  exit_code?: number | null;
  task_count?: number;
  task_id?: string | null;
  run_id?: string | null;
  n_attempts?: number | null;
  note?: string;
};

export type TaskRow = {
  task_id: string;
  status?: string | null;
  score?: number | null;
  run_id?: string | null;
  error?: string | { phase?: string | null; title?: string; message?: string } | null;
  limit?: string | null;
  exit_code?: number | null;
  agent_label?: string;
  model_label?: string;
  reasoning_effort?: string;
  provider_label?: string;
  dataset?: string | null;
  duration?: string | null;
  n?: number | null;
  attempt_run_ids?: string[];
  previous?: Array<{
    run_id?: string | null;
    status?: string | null;
    score?: number | null;
    attempt_index?: number | null;
    started_at?: string | null;
    replaced_at?: string | null;
  }>;
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
  limit?: string | null;
  run_id?: string | null;
  exit_code?: number | null;
  has_evidence?: boolean;
  available_tabs?: string[];
  evidence_relpath?: string | null;
  agent_invocations?: number | null;
  harness_kind?: string | null;
  /** Framework kind, e.g. acp */
  framework?: string | null;
  /** Box kind: local | docker | e2b | ssh */
  environment?: string | null;
  /** Per-role rows for the actors table above Trajectory */
  actors?: Array<{
    role: string;
    agent: string;
    model?: string | null;
    reasoning_effort?: string | null;
    profile_id?: string;
    /** Executor mechanism when present (e.g. acp, nooa). */
    executor_kind?: string | null;
    invokes?: number;
    latency_ms_sum?: number | null;
    /** e.g. "8.3s (1)" — sum of inv latency_ms */
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
    /** e.g. "in 11.4K / out 140 · cache 75% · $0.012" (observational ≠ PASS) */
    usage_label?: string | null;
  }>;
  agent_label?: string | null;
  model_label?: string | null;
  executor_kind?: string | null;
  /** Full lock provenance when present */
  provenance?: Record<string, unknown> | null;
  /** lock.provenance.upstream.url for top-bar link */
  upstream_url?: string | null;
  upstream_name?: string | null;
  upstream_ref?: string | null;
  note?: string | null;
  dataset_id?: string | null;
  dataset_version?: string | null;
  dataset_ref?: string | null;
  /** Attempt-grain observational bag from summary.extra; omit when empty. */
  extra?: Record<string, unknown> | null;
  /** Wall-time phases (environment/run/evaluate/record/cleanup) */
  phase_timing?: {
    schema?: string;
    phases?: Array<{ id: string; label?: string; duration_ms?: number }>;
    total_ms?: number;
    started_at?: string | null;
    finished_at?: string | null;
  } | null;
  /** Aggregated token segments for Harbor-style bar (when usage present) */
  token_timing?: {
    schema?: string;
    segments?: Array<{ id: string; label?: string; tokens?: number }>;
    total_tokens?: number;
  } | null;
};

export type TreeEntry = {
  path: string;
  name: string;
  type: "file" | "dir";
  size?: number | null;
  /** Present on agent/invocations/* entries when metadata has profile_id */
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
  /** Package role profile (actors key); not message role user/assistant */
  profile_id?: string | null;
  model?: string | null;
  line?: number;
  usage?: Record<string, unknown> | null;
  extra?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  /** tool_call / observation (observational; not PASS) */
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
  ended_at?: string | null;
  /** permission_decision (batch auto-approve evidence) */
  outcome?: string | null;
  option_id?: string | null;
  policy?: string | null;
};

export type Breadcrumb = { label: string; href: string | null };

export type DeletePath = {
  locator: string;
  bytes: number;
  role: "suite" | "attempt" | string;
  exists: boolean;
  run_id?: string;
};

export type DeletePreview = {
  ok: boolean;
  job_id: string;
  kind: "suite" | "single" | string;
  can_delete: boolean;
  paths: DeletePath[];
  bytes: number;
  cascade_run_ids: string[];
  confirm_token: string;
  error?: { code?: string; message?: string } | null;
  warning?: { code?: string; message?: string } | null;
};

export type DeleteResult = {
  ok: boolean;
  job_id: string;
  kind: "suite" | "single" | string;
  deleted: string[];
  missing: string[];
  bytes: number;
  cascade_run_ids: string[];
};

let datasetQueryKey: string | null = null;

/** Jobs requests include this directory key when more than one dataset is open. */
export function setDatasetQuery(key: string | null) {
  const text = (key || "").trim();
  datasetQueryKey = text || null;
}

function withDataset(path: string): string {
  if (!datasetQueryKey || !path.startsWith("/api/jobs")) return path;
  const [base, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (!params.has("dataset")) params.set("dataset", datasetQueryKey);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(withDataset(path), { headers: { Accept: "application/json" } });
  const data = (await res.json().catch(() => ({}))) as {
    error?: string;
    message?: string;
  } & T;
  if (!res.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return data as T;
}

export function fetchDeletePreview(jobId: string) {
  return getJson<DeletePreview>(
    `/api/jobs/${encodeURIComponent(jobId)}/delete-preview`,
  );
}

export async function deleteJob(jobId: string, confirmToken: string) {
  const q = new URLSearchParams({ confirm: confirmToken });
  const res = await fetch(withDataset(`/api/jobs/${encodeURIComponent(jobId)}?${q}`), {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const data = (await res.json().catch(() => ({}))) as {
    error?: string;
    message?: string;
  } & DeleteResult;
  if (!res.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return data;
}

export function fetchJobs() {
  return getJson<{
    ok: boolean;
    items: Job[];
    count: number;
    dataset_id?: string;
    version?: string;
    root?: string;
    commands?: Record<string, string>;
  }>("/api/jobs");
}

export function fetchJobOverlays(jobId: string) {
  return getJson<{
    ok: boolean;
    items: TreeEntry[];
    prefixes?: string[];
  }>(`/api/jobs/${encodeURIComponent(jobId)}/overlays`);
}

export function fetchJobOverlayFile(jobId: string, filePath: string) {
  const q = new URLSearchParams({ path: filePath });
  return getJson<{
    ok: boolean;
    path: string;
    size: number;
    encoding: string;
    content: string;
  }>(`/api/jobs/${encodeURIComponent(jobId)}/overlays/file?${q.toString()}`);
}

export function fetchJob(jobId: string) {
  return getJson<{
    ok: boolean;
    job: Job;
    tasks: TaskRow[];
    task_count: number;
    commands?: Record<string, string>;
    note?: string;
  }>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function fetchJobTask(jobId: string, taskId: string) {
  return getJson<{
    ok: boolean;
    job: Job;
    task: TaskRow;
    trials: Trial[];
    agent_label?: string;
    model_label?: string;
    reasoning_effort?: string;
    provider_label?: string;
    dataset?: string;
    commands?: Record<string, string>;
    run_command?: string;
    breadcrumb: Breadcrumb[];
    note?: string;
  }>(
    `/api/jobs/${encodeURIComponent(jobId)}/tasks/${encodeURIComponent(taskId)}`,
  );
}

function trialBase(jobId: string, taskId: string, runId: string) {
  return `/api/jobs/${encodeURIComponent(jobId)}/tasks/${encodeURIComponent(taskId)}/trials/${encodeURIComponent(runId)}`;
}

export function fetchTrial(jobId: string, taskId: string, runId: string) {
  return getJson<{
    ok: boolean;
    job: Job;
    task_id: string;
    trial: Trial;
    result?: Record<string, unknown> | null;
    prev_run_id?: string | null;
    next_run_id?: string | null;
    sibling_run_ids?: string[];
    slot_current_run_id?: string | null;
    slot_current_started_at?: string | null;
    slot_previous?: Array<{
      run_id?: string | null;
      status?: string | null;
      score?: number | null;
      attempt_index?: number | null;
      started_at?: string | null;
      replaced_at?: string | null;
    }>;
    commands?: Record<string, string>;
    run_command?: string;
    breadcrumb: Breadcrumb[];
    note?: string;
  }>(trialBase(jobId, taskId, runId));
}

export function fetchTrialTree(
  jobId: string,
  taskId: string,
  runId: string,
  scope: string,
) {
  const q = new URLSearchParams({ scope });
  return getJson<{
    ok: boolean;
    run_id: string;
    scope: string;
    entries: TreeEntry[];
    /** Virtual profile groups for Agent tab (paths stay real) */
    groups?: Array<{
      key: string;
      profile_id?: string | null;
      label?: string;
    }> | null;
    truncated?: boolean;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/tree?${q}`);
}

export function fetchTrialFile(
  jobId: string,
  taskId: string,
  runId: string,
  path: string,
) {
  const q = new URLSearchParams({ path });
  return getJson<{
    ok: boolean;
    run_id: string;
    path: string;
    name: string;
    size: number;
    media_type: string;
    encoding: string;
    truncated?: boolean;
    content?: string | null;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/file?${q}`);
}

export function fetchTrialTrajectory(jobId: string, taskId: string, runId: string) {
  return getJson<{
    ok: boolean;
    run_id: string;
    task_id: string;
    steps: TrajectoryStep[];
    step_count: number;
    invocations: Array<{
      dirname: string;
      invocation_id?: string;
      profile_id?: string;
      executor_kind?: string;
      model?: string;
      status?: string;
      step_count?: number;
      has_trajectory?: boolean;
    }>;
    truncated?: boolean;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/trajectory`);
}

export function fetchTrialObservation(jobId: string, taskId: string, runId: string) {
  return getJson<{
    ok: boolean;
    run_id: string;
    task_id: string;
    steps: TrajectoryStep[];
    step_count: number;
    truncated?: boolean;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/observation`);
}

export function fetchTrialChecks(jobId: string, taskId: string, runId: string) {
  return getJson<{
    ok: boolean;
    run_id: string;
    task_id: string;
    schema: string | null;
    checks: Array<Record<string, unknown>>;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/checks`);
}

export function fetchTrialPackageFile(
  jobId: string,
  taskId: string,
  runId: string,
  path: string,
) {
  const q = new URLSearchParams({ path });
  return getJson<{
    ok: boolean;
    run_id: string;
    path: string;
    name: string;
    size: number;
    encoding: string;
    truncated?: boolean;
    content?: string | null;
    note?: string;
  }>(`${trialBase(jobId, taskId, runId)}/package-file?${q}`);
}

export type DatasetItem = {
  key: string;
  dataset_id: string;
  version: string;
  description?: string | null;
  task_count: number;
  label: string;
};

export type ViewSession = {
  ok: boolean;
  mode: string;
  landing: "jobs" | "datasets" | string;
  dataset_count: number;
  datasets: DatasetItem[];
};

export type CatalogItem = {
  source: "builtin" | "installed" | string;
  id: string;
  version: string;
  label: string;
  description?: string | null;
  read_only?: boolean;
};

export type PackageDetail = {
  ok: boolean;
  kind: string;
  source: string;
  id: string;
  version: string;
  label: string;
  description?: string | null;
  readme?: string | null;
  manifest?: string | null;
  profiles?: string | null;
  read_only?: boolean;
  declared?: {
    id: string;
    kind: "exclusive" | "chain";
    entry?: string;
    priority?: number;
  }[];
};

export type PackageFile = {
  ok: boolean;
  path: string;
  name: string;
  size: number;
  encoding: string;
  truncated?: boolean;
  content?: string | null;
  note?: string | null;
};

export function fetchSession() {
  return getJson<ViewSession>("/api/session");
}

export function fetchDataset(key: string) {
  return getJson<PackageDetail>(`/api/datasets/${encodeURIComponent(key)}`);
}

export function fetchDatasetTree(key: string) {
  return getJson<{ ok: boolean; entries: TreeEntry[] }>(
    `/api/datasets/${encodeURIComponent(key)}/tree`,
  );
}

export function fetchDatasetFile(key: string, path: string) {
  const q = new URLSearchParams({ path });
  return getJson<PackageFile>(
    `/api/datasets/${encodeURIComponent(key)}/file?${q}`,
  );
}

function catalogQuery(source: string, id: string, version: string, path?: string) {
  const q = new URLSearchParams({ source, id, version });
  if (path) q.set("path", path);
  return q.toString();
}

export function fetchPlugins() {
  return getJson<{ ok: boolean; items: CatalogItem[] }>("/api/plugins");
}

export function fetchPlugin(source: string, id: string, version: string) {
  return getJson<PackageDetail>(`/api/plugins/package?${catalogQuery(source, id, version)}`);
}

export function fetchPluginTree(source: string, id: string, version: string) {
  return getJson<{ ok: boolean; entries: TreeEntry[] }>(
    `/api/plugins/tree?${catalogQuery(source, id, version)}`,
  );
}

export function fetchPluginFile(source: string, id: string, version: string, path: string) {
  return getJson<PackageFile>(
    `/api/plugins/file?${catalogQuery(source, id, version, path)}`,
  );
}

export function fetchAgents() {
  return getJson<{ ok: boolean; items: CatalogItem[] }>("/api/agents");
}

export function fetchAgent(source: string, id: string, version: string) {
  return getJson<PackageDetail>(`/api/agents/package?${catalogQuery(source, id, version)}`);
}

export function fetchAgentTree(source: string, id: string, version: string) {
  return getJson<{ ok: boolean; entries: TreeEntry[] }>(
    `/api/agents/tree?${catalogQuery(source, id, version)}`,
  );
}

export function fetchAgentFile(source: string, id: string, version: string, path: string) {
  return getJson<PackageFile>(
    `/api/agents/file?${catalogQuery(source, id, version, path)}`,
  );
}
