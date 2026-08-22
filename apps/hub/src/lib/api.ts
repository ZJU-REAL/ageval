/** Registry HTTP client for Hub SPA (#39 / #40). */

export type DeclaredSlot = {
  id: string;
  kind: "exclusive" | "chain";
  entry?: string;
  priority?: number;
  level?: number;
};

export type PluginPreview = {
  plugin_id?: string;
  version?: string;
  format?: string;
  description?: string | null;
  slots?: {
    exclusive?: string[];
    chain?: string[];
  };
  declared?: DeclaredSlot[];
  files?: string[];
};

export type AgentPreview = {
  agent_id?: string;
  version?: string;
  format?: string;
  label?: string | null;
  description?: string | null;
  tags?: string[];
  /** Secret-free job binding (design/14): executor/model/options/extensions. */
  binding?: Record<string, unknown>;
  files?: string[];
};

export type SuitePluginRef = {
  plugin_id: string;
  version?: string;
};

const BUILTIN_EXECUTOR_KINDS = new Set(["acp", "openai-http"]);

export type PackageRelease = {
  dataset_id: string;
  version: string;
  visibility: string;
  package_digest: string;
  blob_digest: string;
  size: number;
  media_type?: string;
  /** Registry package_kind: dataset | plugin | agent. */
  package_kind?: "dataset" | "plugin" | "agent" | string;
  created_at?: number;
  org_id?: string;
  /** Registry marketplace display: upload org is on the official-org allowlist. */
  official?: boolean;
  /** Present on by-digest / version get for plugins. */
  plugin_preview?: PluginPreview;
  /** Present on by-digest / version get for agents (design/14). */
  agent_preview?: AgentPreview;
  /** Draft slot (entitled callers only). */
  is_draft?: boolean;
  slot?: string;
  uploaded_by?: string;
  /** Owner-set marketplace title; id stays dataset_id. */
  display_name?: string;
  /** Closed-catalog mark; omit means GitHub avatar (icon_github or uploader). */
  icon_key?: string;
  /** GitHub login override for the entity mark. */
  icon_github?: string;
  /** Marketplace observation: successful content GETs for this package id. */
  download_count?: number;
  /** Marketplace observation: signed-in users who favorited this package id. */
  favorite_count?: number;
  /** True when the current caller has favorited this package. */
  favorited?: boolean;
};

export type OrgRow = {
  org_id: string;
  name: string;
  display_name?: string;
  description?: string;
  is_claimable?: boolean;
  created_at?: number;
  role?: string;
  /** Upload org is on the Registry official-org allowlist. */
  official?: boolean;
};

export type OrgMember = {
  org_id: string;
  user_id: string;
  role: string;
  created_at?: number;
  /** GitHub profile display name (from login-time profile snapshot). */
  display_name?: string;
  avatar_url?: string;
  github_id?: string;
};

export type UserOfficialOrg = {
  org_id: string;
  display_name?: string;
  official: true;
};

export type UserPublic = {
  user_id: string;
  display_name?: string;
  avatar_url?: string;
  description?: string;
  official: boolean;
  official_orgs: UserOfficialOrg[];
};

export type OrgInviteKey = {
  key_id: string;
  org_id: string;
  token_prefix: string;
  created_by?: string;
  max_uses?: number | null;
  use_count?: number;
  expires_at?: number | null;
  revoked_at?: number | null;
  created_at?: number;
  active?: boolean;
  /** Full secret — create response only; omitted from list/revoke. */
  invite_key?: string;
};

export type ResultShare = {
  result_kind: string;
  result_id: string;
  target_type: string;
  target_id: string;
  created_at?: number;
};

export type FileItem = {
  path: string;
  type: "file" | "dir" | string;
  size: number;
};

export type TreeEntry = {
  path: string;
  name: string;
  type?: string;
  size?: number;
};

export type FileContent = {
  path: string;
  size: number;
  encoding: "utf-8" | "base64" | string;
  content: string;
  truncated?: boolean;
};

export type JobOverlayProfile = {
  executor?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  label?: string;
  agent_ref?: string;
  options?: { entry?: string; reasoning_effort?: string };
  overlays?: string[];
  extensions?: Array<{ plugin?: string; options?: Record<string, unknown> }>;
};

/** Current lock/suite overlay: box kind + agent_profiles. */
export type JobOverlay = {
  environment?: string;
  environment_options?: Record<string, unknown>;
  agent_profiles?: Record<string, JobOverlayProfile>;
};

export function overlayAgentProfiles(
  overlay: JobOverlay | null | undefined,
): Record<string, JobOverlayProfile> {
  const profiles = overlay?.agent_profiles;
  if (!profiles || typeof profiles !== "object") return {};
  return profiles;
}

export function environmentFromOverlay(
  overlay: JobOverlay | null | undefined,
): string | null {
  const env = overlay?.environment;
  if (typeof env === "string" && env.trim()) return env.trim();
  return null;
}

export type SuiteRow = {
  suite_run_id: string;
  dataset_id?: string;
  dataset_version?: string;
  visibility?: string;
  pass_rate?: number | null;
  mean_score?: number | null;
  /**
   * Observational suite metrics blob (Registry metrics_json).
   * May include pass_at_k / pass_power_k / n_attempts / k_values / per_task (#60).
   * Never suite-level PASS.
   */
  metrics?: Record<string, unknown>;
  task_refs?: Array<{
    task_id?: string;
    status?: string | null;
    score?: number | null;
    run_id?: string | null;
    /** Multi-attempt sample counts (#60 A3). */
    n?: number | null;
    c?: number | null;
    /** All attempt run_ids for audit / --with-attempts. */
    attempt_run_ids?: string[];
    /** True when full Attempt evidence archive is present on Registry (#43). */
    has_attempt_content?: boolean;
    /** Superseded Attempts for this scoring slot (oldest first). */
    previous?: Array<{
      run_id?: string | null;
      status?: string | null;
      score?: number | null;
      attempt_index?: number | null;
      started_at?: string | null;
      replaced_at?: string | null;
    }>;
  }>;
  agent_label?: string;
  model_label?: string;
  config_fingerprint?: string;
  config_homogeneous?: boolean;
  actors_summary?: Array<Record<string, string>>;
  /** Secret-free job binding (#59) for rehydrate / re-run. */
  job_overlay?: JobOverlay;
  /** Secret-free marketplace plugins used by this job. */
  plugins?: SuitePluginRef[];
  exit_code?: number | null;
  created_at?: number | string;
  note?: string;
  uploaded_by?: string;
  /** Stored at upload; complete ≠ suite PASS. */
  complete?: boolean;
  bound_kind?: "release" | "draft" | "unknown" | string;
  task_set_digest?: string;
  /** Dataset-org listing approval; public ≠ listed. */
  board_listed?: boolean;
  /** Official public board only; derived from consented published agent_ref. */
  agent_refs?: AgentRefLink[];
};

export type AgentRefLink = {
  role: string;
  package_id: string;
};

export type RuntimeTeammate = {
  role: string;
  executor: string;
  entry: string;
  display_name: string;
};

export type AgentAppearance = {
  package_id: string;
  agent_version: string;
  dataset_id: string;
  dataset_version?: string;
  package_digest?: string;
  suite_run_id: string;
  role: string;
  model: string;
  pass_rate?: number | null;
  mean_score?: number | null;
  metrics?: Record<string, unknown>;
  uploaded_by?: string;
  created_at?: number;
  teammates?: RuntimeTeammate[];
  overlays?: string[];
  agent_ref?: string;
};

/** Published Hub id + version from an agent_ref. Null for file:/local/ refs. */
export function parsePublishedAgentRef(
  ref: string | undefined | null,
): { packageId: string; version: string; digest12: string } | null {
  if (!ref || ref.startsWith("file:")) return null;
  const at = ref.indexOf("@");
  if (at <= 0) return null;
  const packageId = ref.slice(0, at);
  if (!packageId.includes("/") || packageId.startsWith("local/")) return null;
  const rest = ref.slice(at + 1);
  const plus = rest.indexOf("+");
  const version = (plus >= 0 ? rest.slice(0, plus) : rest).trim();
  if (!version) return null;
  const digestPart = plus >= 0 ? rest.slice(plus + 1).trim() : "";
  const digest12 = digestPart.startsWith("sha256:")
    ? digestPart.slice("sha256:".length)
    : digestPart;
  return { packageId, version, digest12 };
}

/** Hub package id from an agent_ref (`org/name@ver+sha…`); null for local/file refs. */
export function agentRefPackageId(ref: string | undefined | null): string | null {
  if (!ref || ref.startsWith("file:")) return null;
  const id = ref.split("@", 1)[0] ?? "";
  if (!id.includes("/") || id.startsWith("local/")) return null;
  return id;
}

function overlayPathList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    const path = String(item || "").trim();
    if (!path.startsWith("overlays/") || seen.has(path)) continue;
    seen.add(path);
    out.push(path);
  }
  return out;
}

/** Split job_overlay overlay paths: Dataset (no published agent_ref) vs Agent packages. */
export function splitJobOverlaySources(
  overlay: SuiteRow["job_overlay"] | null | undefined,
): {
  jobPrefixes: string[];
  agents: { ref: string; packageId: string; prefixes: string[] }[];
} {
  const jobPrefixes: string[] = [];
  const jobSeen = new Set<string>();
  const byPackage = new Map<string, { ref: string; prefixes: string[]; seen: Set<string> }>();
  const profiles = overlayAgentProfiles(overlay);
  if (!Object.keys(profiles).length) return { jobPrefixes, agents: [] };
  for (const raw of Object.values(profiles)) {
    if (!raw) continue;
    const paths = overlayPathList(raw.overlays);
    if (!paths.length) continue;
    const parsed = parsePublishedAgentRef(raw.agent_ref);
    if (parsed) {
      let group = byPackage.get(parsed.packageId);
      if (!group) {
        group = { ref: String(raw.agent_ref).trim(), prefixes: [], seen: new Set() };
        byPackage.set(parsed.packageId, group);
      }
      for (const path of paths) {
        if (group.seen.has(path)) continue;
        group.seen.add(path);
        group.prefixes.push(path);
      }
      continue;
    }
    for (const path of paths) {
      if (jobSeen.has(path)) continue;
      jobSeen.add(path);
      jobPrefixes.push(path);
    }
  }
  return {
    jobPrefixes,
    agents: [...byPackage.entries()].map(([packageId, group]) => ({
      ref: group.ref,
      packageId,
      prefixes: group.prefixes,
    })),
  };
}

/** Full package digest for a published agent_ref (short digest prefix-matched). */
export async function resolveAgentPackageDigest(
  ref: string,
  token: string | null,
): Promise<{ packageId: string; digest: string } | null> {
  const parsed = parsePublishedAgentRef(ref);
  if (!parsed) return null;
  const versions = await listPackageVersions(parsed.packageId, token);
  const match =
    versions.find((row) => {
      if (row.version !== parsed.version) return false;
      if (!parsed.digest12) return true;
      const hex = (row.package_digest || "").replace(/^sha256:/, "");
      return hex.startsWith(parsed.digest12);
    }) ?? versions.find((row) => row.version === parsed.version);
  if (!match?.package_digest) return null;
  return { packageId: parsed.packageId, digest: match.package_digest };
}

export type AttemptMeta = {
  run_id: string;
  dataset_id?: string;
  task_id?: string;
  status?: string;
  visibility?: string;
  blob_digest?: string;
  size?: number;
  created_at?: number | string;
  uploaded_by?: string;
  suite_run_id?: string;
  lock_digest?: string;
  environment?: string;
  agent_label?: string;
  model_label?: string;
  score?: number | null;
};

export async function listAttempts(
  datasetId: string | null,
  token: string | null,
  opts?: { taskId?: string; standalone?: boolean },
): Promise<AttemptMeta[]> {
  const q = new URLSearchParams();
  if (datasetId) q.set("dataset_id", datasetId);
  if (opts?.taskId) q.set("task_id", opts.taskId);
  if (opts?.standalone) q.set("standalone", "1");
  const path = q.toString()
    ? `/v1/results/attempts?${q.toString()}`
    : "/v1/results/attempts";
  const data = await requestJson<{ items?: AttemptMeta[] }>(path, { token });
  return Array.isArray(data.items) ? data.items : [];
}

export class RegistryHttpError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function registryBase(): string {
  const raw = import.meta.env.VITE_REGISTRY_URL as string | undefined;
  if (raw && raw.trim()) return raw.replace(/\/$/, "");
  // Dev: same-origin → Vite proxy to Registry.
  return "";
}

function authHeaders(token: string | null): HeadersInit {
  const h: Record<string, string> = { Accept: "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function requestJson<T>(
  path: string,
  opts: { token?: string | null; method?: string; body?: unknown } = {},
): Promise<T> {
  const url = `${registryBase()}${path}`;
  const res = await fetch(url, {
    method: opts.method || "GET",
    headers: {
      ...authHeaders(opts.token ?? null),
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  let data: unknown = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { message: text };
  }
  if (!res.ok) {
    const obj = data as { error?: string; message?: string };
    throw new RegistryHttpError(
      res.status,
      String(obj.error || "http_error"),
      String(obj.message || res.statusText || "request failed"),
    );
  }
  return data as T;
}

export function encodeDatasetId(id: string): string {
  return encodeURIComponent(id);
}

/** Hub plugin/package id is ``org/name``. Display edits only the name leaf. */
export function splitPackageId(id: string): { org: string | null; name: string } {
  const slash = id.indexOf("/");
  if (slash <= 0 || slash === id.length - 1) return { org: null, name: id };
  return { org: id.slice(0, slash), name: id.slice(slash + 1) };
}

export function packageDisplayTitle(id: string, displayName?: string | null): string {
  const { org, name } = splitPackageId(id);
  const leaf = (displayName || "").trim() || name;
  return org ? `${org}/${leaf}` : leaf;
}

export function decodeDatasetId(param: string): string {
  return decodeURIComponent(param);
}

export async function listPackages(
  token: string | null,
  opts?: {
    packageKind?: "dataset" | "plugin" | "agent";
    mine?: boolean;
    favorited?: boolean;
    orgs?: boolean;
    visibility?: "public" | "private";
  },
): Promise<PackageRelease[]> {
  // With token, server may include private; without, public only.
  const q = new URLSearchParams();
  if (opts?.packageKind) q.set("package_kind", opts.packageKind);
  if (opts?.mine) q.set("mine", "1");
  if (opts?.favorited) q.set("favorited", "1");
  if (opts?.orgs) q.set("orgs", "1");
  if (opts?.visibility) q.set("visibility", opts.visibility);
  const path = q.toString() ? `/v1/packages?${q.toString()}` : "/v1/packages";
  const data = await requestJson<{ items?: PackageRelease[] }>(path, {
    token,
  });
  return Array.isArray(data.items) ? data.items : [];
}

export async function setPackageFavorite(
  packageId: string,
  favorited: boolean,
  token: string | null,
): Promise<{
  dataset_id: string;
  favorite_count: number;
  favorited: boolean;
}> {
  return requestJson(`/v1/packages/${packageIdPath(packageId)}/favorite`, {
    token,
    method: favorited ? "POST" : "DELETE",
  });
}

export async function listPackageVersionsWithAppearances(
  datasetId: string,
  token: string | null,
): Promise<{ items: PackageRelease[]; appearances: AgentAppearance[] }> {
  const path = `/v1/packages/${datasetId.split("/").map(encodeURIComponent).join("/")}`;
  const data = await requestJson<{
    items?: PackageRelease[];
    appearances?: AgentAppearance[];
  }>(path, { token });
  return {
    items: Array.isArray(data.items) ? data.items : [],
    appearances: Array.isArray(data.appearances) ? data.appearances : [],
  };
}

export async function listPackageVersions(
  datasetId: string,
  token: string | null,
): Promise<PackageRelease[]> {
  return (await listPackageVersionsWithAppearances(datasetId, token)).items;
}

/** Package meta by digest (includes plugin_preview for ageval.plugin/1). */
export async function getPackageByDigest(
  packageId: string,
  digest: string,
  token: string | null,
): Promise<PackageRelease> {
  const id = packageIdPath(packageId);
  const dig = digestPath(digest);
  return requestJson(`/v1/packages/${id}/by-digest/${dig}`, { token });
}

export function isDraftRelease(row: PackageRelease): boolean {
  return Boolean(row.is_draft || row.slot === "draft" || row.version === "draft");
}

export function versionLabel(row: PackageRelease): string {
  return isDraftRelease(row) ? "draft" : `v${row.version}`;
}

/** Prefer latest release; fall back to draft when that is the only slot. */
export function pickPackageVersion(
  versions: PackageRelease[],
  requested?: string | null,
): PackageRelease | null {
  if (!versions.length) return null;
  if (requested) {
    const hit = versions.find((v) => v.version === requested);
    if (hit) return hit;
  }
  const releases = versions.filter((v) => !isDraftRelease(v));
  const pool = releases.length ? releases : versions;
  return [...pool].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
}

/** One catalog row per dataset_id. Draft is never preferred over a release. */
export function latestPackageByDataset(
  items: PackageRelease[],
): PackageRelease[] {
  const byId = new Map<string, PackageRelease[]>();
  for (const row of items) {
    const list = byId.get(row.dataset_id) ?? [];
    list.push(row);
    byId.set(row.dataset_id, list);
  }
  const out: PackageRelease[] = [];
  for (const rows of byId.values()) {
    const picked = pickPackageVersion(rows);
    if (picked) out.push(picked);
  }
  return out.sort((a, b) => a.dataset_id.localeCompare(b.dataset_id));
}

export function isPluginPackage(row: PackageRelease): boolean {
  return row.package_kind === "plugin";
}

export function isDatasetPackage(row: PackageRelease): boolean {
  return row.package_kind === "dataset";
}

function packageIdPath(datasetId: string): string {
  return datasetId.split("/").map(encodeURIComponent).join("/");
}

/** Keep ``sha256:`` colon unescaped (matches Registry path regex). */
function digestPath(digest: string): string {
  if (digest.startsWith("sha256:")) {
    return `sha256:${encodeURIComponent(digest.slice("sha256:".length))}`;
  }
  return encodeURIComponent(digest);
}

export async function listPackageFiles(
  datasetId: string,
  digest: string,
  token: string | null,
): Promise<{ items: FileItem[]; digest: string; version?: string }> {
  const id = packageIdPath(datasetId);
  const dig = digestPath(digest);
  return requestJson(`/v1/packages/${id}/by-digest/${dig}/files`, { token });
}

export async function getPackageFile(
  datasetId: string,
  digest: string,
  filePath: string,
  token: string | null,
): Promise<FileContent> {
  const id = packageIdPath(datasetId);
  const dig = digestPath(digest);
  const fp = filePath
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
  return requestJson(`/v1/packages/${id}/by-digest/${dig}/files/${fp}`, { token });
}

export async function listSuites(
  datasetId: string | null,
  token: string | null,
  opts?: { board?: boolean; uploadedBy?: string },
): Promise<SuiteRow[]> {
  const q = new URLSearchParams();
  if (datasetId) q.set("dataset_id", datasetId);
  if (opts?.board) q.set("board", "1");
  if (opts?.uploadedBy) q.set("uploaded_by", opts.uploadedBy);
  const path = q.toString()
    ? `/v1/results/suites?${q.toString()}`
    : "/v1/results/suites";
  const data = await requestJson<{ items?: SuiteRow[] }>(path, { token });
  return Array.isArray(data.items) ? data.items : [];
}

export function uniqueAgentRefs(refs: AgentRefLink[] | undefined): AgentRefLink[] {
  if (!refs?.length) return [];
  const seen = new Set<string>();
  const out: AgentRefLink[] = [];
  for (const ref of refs) {
    const id = (ref.package_id || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(ref);
  }
  return out;
}

export async function getAttempt(
  runId: string,
  token: string | null,
): Promise<AttemptMeta> {
  return requestJson(`/v1/results/attempts/${encodeURIComponent(runId)}`, {
    token,
  });
}

export async function listAttemptFiles(
  runId: string,
  token: string | null,
): Promise<{ run_id: string; items: FileItem[]; digest?: string }> {
  return requestJson(
    `/v1/results/attempts/${encodeURIComponent(runId)}/files`,
    { token },
  );
}

export async function getAttemptFile(
  runId: string,
  filePath: string,
  token: string | null,
): Promise<FileContent> {
  const fp = filePath
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
  return requestJson(
    `/v1/results/attempts/${encodeURIComponent(runId)}/files/${fp}`,
    { token },
  );
}

export async function getUser(userId: string): Promise<UserPublic> {
  return requestJson(`/v1/users/${encodeURIComponent(userId)}`);
}

export async function listOrgs(token: string | null): Promise<OrgRow[]> {
  const data = await requestJson<{ items?: OrgRow[] }>("/v1/orgs", { token });
  return Array.isArray(data.items) ? data.items : [];
}

export async function createOrg(
  body: { name: string; display_name?: string; description?: string },
  token: string | null,
): Promise<OrgRow> {
  return requestJson("/v1/orgs", {
    token,
    method: "POST",
    body: {
      name: body.name,
      display_name: body.display_name || body.name,
      ...(body.description != null ? { description: body.description } : {}),
    },
  });
}

export async function getOrg(
  orgId: string,
  token: string | null,
): Promise<OrgRow> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}`, { token });
}

export async function updateOrgDisplayName(
  orgId: string,
  displayName: string,
  token: string | null,
): Promise<OrgRow> {
  return updateOrg(orgId, { display_name: displayName }, token);
}

export async function updateOrg(
  orgId: string,
  body: { display_name?: string; description?: string },
  token: string | null,
): Promise<OrgRow> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}`, {
    token,
    method: "PATCH",
    body,
  });
}

export async function updateUserDescription(
  userId: string,
  description: string,
  token: string | null,
): Promise<UserPublic> {
  return requestJson(`/v1/users/${encodeURIComponent(userId)}`, {
    token,
    method: "PATCH",
    body: { description },
  });
}

export async function updatePackageDisplayName(
  packageId: string,
  displayName: string,
  token: string | null,
): Promise<PackageRelease> {
  return requestJson(`/v1/packages/${packageIdPath(packageId)}`, {
    token,
    method: "PATCH",
    body: { display_name: displayName },
  });
}

export async function updatePackageIcon(
  packageId: string,
  body: { icon_key: string; icon_github: string },
  token: string | null,
): Promise<PackageRelease> {
  return requestJson(`/v1/packages/${packageIdPath(packageId)}`, {
    token,
    method: "PATCH",
    body,
  });
}

export async function setPackageVisibility(
  packageId: string,
  version: string,
  visibility: "public" | "private",
  token: string | null,
): Promise<PackageRelease> {
  return requestJson(
    `/v1/packages/${packageIdPath(packageId)}/versions/${encodeURIComponent(version)}`,
    { token, method: "PATCH", body: { visibility } },
  );
}

export async function deletePackageRelease(
  packageId: string,
  version: string,
  token: string | null,
): Promise<{ ok?: boolean }> {
  return requestJson(
    `/v1/packages/${packageIdPath(packageId)}/versions/${encodeURIComponent(version)}`,
    { token, method: "DELETE" },
  );
}

export async function releasePackageDraft(
  packageId: string,
  body: {
    visibility?: "public" | "private";
    version?: string;
    replace?: boolean;
  },
  token: string | null,
): Promise<PackageRelease> {
  return requestJson(`/v1/packages/${packageIdPath(packageId)}/release`, {
    token,
    method: "POST",
    body,
  });
}

export async function listOrgMembers(
  orgId: string,
  token: string | null,
): Promise<OrgMember[]> {
  const data = await requestJson<{ items?: OrgMember[] }>(
    `/v1/orgs/${encodeURIComponent(orgId)}/members`,
    { token },
  );
  return Array.isArray(data.items) ? data.items : [];
}

export async function addOrgMember(
  orgId: string,
  userId: string,
  token: string | null,
  role: "owner" | "member" = "member",
): Promise<OrgMember> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}/members`, {
    token,
    method: "POST",
    body: { user_id: userId, role },
  });
}

export async function setOrgMemberRole(
  orgId: string,
  userId: string,
  role: "owner" | "member",
  token: string | null,
): Promise<OrgMember> {
  return requestJson(
    `/v1/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`,
    { token, method: "PATCH", body: { role } },
  );
}

export async function removeOrgMember(
  orgId: string,
  userId: string,
  token: string | null,
): Promise<{ ok: boolean; org_id: string; user_id: string }> {
  return requestJson(
    `/v1/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`,
    { token, method: "DELETE" },
  );
}

export type OrgTransferResult = {
  ok: boolean;
  org_id: string;
  from: OrgMember;
  to: OrgMember;
};

export async function transferOrg(
  orgId: string,
  userId: string,
  token: string | null,
): Promise<OrgTransferResult> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}/transfer`, {
    token,
    method: "POST",
    body: { user_id: userId },
  });
}

export async function joinOrgWithInvite(
  inviteKey: string,
  token: string | null,
): Promise<OrgRow & { role?: string }> {
  return requestJson("/v1/orgs/join", {
    token,
    method: "POST",
    body: { invite_key: inviteKey },
  });
}

export async function listOrgInviteKeys(
  orgId: string,
  token: string | null,
): Promise<OrgInviteKey[]> {
  const data = await requestJson<{ items?: OrgInviteKey[] }>(
    `/v1/orgs/${encodeURIComponent(orgId)}/invite-keys`,
    { token },
  );
  return Array.isArray(data.items) ? data.items : [];
}

export async function createOrgInviteKey(
  orgId: string,
  body: { max_uses?: number | null; expires_in_days?: number | null },
  token: string | null,
): Promise<OrgInviteKey> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}/invite-keys`, {
    token,
    method: "POST",
    body,
  });
}

export async function revokeOrgInviteKey(
  orgId: string,
  keyId: string,
  token: string | null,
): Promise<OrgInviteKey> {
  return requestJson(
    `/v1/orgs/${encodeURIComponent(orgId)}/invite-keys/${encodeURIComponent(keyId)}`,
    { token, method: "DELETE" },
  );
}

/** Current user leaves org (sole owner must dissolve instead). */
export async function leaveOrg(
  orgId: string,
  token: string | null,
): Promise<{ ok: boolean; org_id: string }> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}/leave`, {
    token,
    method: "POST",
    body: {},
  });
}

/** Owner dissolves org (fails if packages still bound). */
export async function dissolveOrg(
  orgId: string,
  token: string | null,
): Promise<{ ok: boolean; org_id: string }> {
  return requestJson(`/v1/orgs/${encodeURIComponent(orgId)}`, {
    token,
    method: "DELETE",
  });
}

export async function listResultShares(
  kind: "attempt" | "suite",
  resultId: string,
  token: string | null,
): Promise<ResultShare[]> {
  const kindPath = kind === "attempt" ? "attempts" : "suites";
  const data = await requestJson<{ items?: ResultShare[] }>(
    `/v1/results/${kindPath}/${encodeURIComponent(resultId)}/shares`,
    { token },
  );
  return Array.isArray(data.items) ? data.items : [];
}

function resultPath(kind: "attempt" | "suite", resultId: string): string {
  const kindPath = kind === "attempt" ? "attempts" : "suites";
  return `/v1/results/${kindPath}/${encodeURIComponent(resultId)}`;
}

export async function addResultShare(
  kind: "attempt" | "suite",
  resultId: string,
  target: { type: "org" | "user"; id: string },
  token: string | null,
): Promise<ResultShare> {
  return requestJson(`${resultPath(kind, resultId)}/shares`, {
    token,
    method: "POST",
    body: { target_type: target.type, target_id: target.id },
  });
}

export async function removeResultShare(
  kind: "attempt" | "suite",
  resultId: string,
  target: { type: "org" | "user"; id: string },
  token: string | null,
): Promise<{ ok: boolean }> {
  return requestJson(`${resultPath(kind, resultId)}/shares`, {
    token,
    method: "DELETE",
    body: { target_type: target.type, target_id: target.id },
  });
}

export type ResourceRequest = {
  request_id: string;
  kind: "leaderboard_list" | "agent_appearance" | string;
  status: "pending" | "approved" | "rejected" | string;
  suite_run_id: string;
  dataset_id: string;
  applicant: string;
  owner_org_id: string;
  agent_ref?: string;
  created_at?: number;
  decided_at?: number;
  decided_by?: string;
};

export async function applyRequest(
  body: { kind: string; suite_run_id: string; agent?: string },
  token: string | null,
): Promise<ResourceRequest & { direct_attach?: boolean; attached?: boolean }> {
  return requestJson("/v1/requests", { token, method: "POST", body });
}

export async function listInbox(
  token: string | null,
): Promise<ResourceRequest[]> {
  const data = await requestJson<{ items?: ResourceRequest[] }>(
    "/v1/requests?inbox=1",
    { token },
  );
  return Array.isArray(data.items) ? data.items : [];
}

export async function decideRequests(
  ids: string[],
  action: "approve" | "reject",
  token: string | null,
): Promise<{ items?: ResourceRequest[]; action?: string }> {
  return requestJson("/v1/requests/decide", {
    token,
    method: "POST",
    body: { ids, action },
  });
}

export async function attachSuiteAgent(
  suiteRunId: string,
  agent: string,
  token: string | null,
  opts?: { role?: string },
): Promise<SuiteRow & { attached?: boolean; idempotent?: boolean }> {
  const body: { agent: string; role?: string } = { agent };
  if (opts?.role) body.role = opts.role;
  return requestJson(
    `/v1/results/suites/${encodeURIComponent(suiteRunId)}/agent-ref`,
    { token, method: "PATCH", body },
  );
}

export async function setResultVisibility(
  kind: "attempt" | "suite",
  resultId: string,
  visibility: "public" | "private",
  token: string | null,
): Promise<{ visibility?: string }> {
  return requestJson(resultPath(kind, resultId), {
    token,
    method: "PATCH",
    body: { visibility },
  });
}

export async function deleteResult(
  kind: "attempt" | "suite",
  resultId: string,
  token: string | null,
  opts?: { withAttempts?: boolean },
): Promise<{ ok?: boolean }> {
  const extra =
    kind === "suite" && opts?.withAttempts ? "?with_attempts=1" : "";
  return requestJson(`${resultPath(kind, resultId)}${extra}`, {
    token,
    method: "DELETE",
  });
}

export async function deviceCode(): Promise<{
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete?: string;
  interval?: number;
  expires_in?: number;
}> {
  return requestJson("/v1/auth/github/device/code", {
    method: "POST",
    body: {},
  });
}

/** Hub browser OAuth (Authorization Code) — Harbor-style, no device user_code. */
export async function startWebLogin(
  redirectUri: string,
): Promise<{ authorize_url: string; state: string }> {
  return requestJson("/v1/auth/github/web/start", {
    method: "POST",
    body: { redirect_uri: redirectUri },
  });
}

export async function completeWebLogin(opts: {
  code: string;
  state: string;
  redirectUri: string;
}): Promise<{
  token: string;
  github_user?: string;
  github_name?: string;
  github_id?: number;
  avatar_url?: string;
  scopes?: string[];
}> {
  return requestJson("/v1/auth/github/web/callback", {
    method: "POST",
    body: {
      code: opts.code,
      state: opts.state,
      redirect_uri: opts.redirectUri,
    },
  });
}

/**
 * Device poll. Registry returns 202 while pending (not an error).
 * Success 200: ``{ token, github_user, scopes }`` (Registry API token, not GH).
 */
export async function devicePoll(
  deviceCodeValue: string,
  opts?: { signal?: AbortSignal },
): Promise<{
  status?: string;
  token?: string;
  access_token?: string;
  github_user?: string;
  github_name?: string;
  github_id?: number;
  avatar_url?: string;
  message?: string;
  error?: string;
}> {
  const url = `${registryBase()}/v1/auth/github/device/poll`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ device_code: deviceCodeValue }),
    signal: opts?.signal,
  });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  try {
    data = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    data = { message: text };
  }
  // 202 Accepted = still waiting (must not throw — res.ok is true for 202,
  // but we normalize explicitly for clarity).
  if (res.status === 202 || data.status === "authorization_pending") {
    return {
      status: "authorization_pending",
      message: String(data.message || "waiting for user"),
    };
  }
  if (!res.ok) {
    throw new RegistryHttpError(
      res.status,
      String(data.error || "http_error"),
      String(data.message || res.statusText || "poll failed"),
    );
  }
  return {
    status: "ok",
    token: typeof data.token === "string" ? data.token : undefined,
    access_token:
      typeof data.access_token === "string" ? data.access_token : undefined,
    github_user:
      typeof data.github_user === "string" ? data.github_user : undefined,
    github_name:
      typeof data.github_name === "string" ? data.github_name : undefined,
    github_id: typeof data.github_id === "number" ? data.github_id : undefined,
    avatar_url:
      typeof data.avatar_url === "string" ? data.avatar_url : undefined,
  };
}

/** Prefer file entries under tasks/<id>/ (exclude dirs). */
export function filesToTree(items: FileItem[], prefix?: string): TreeEntry[] {
  const files = items.filter((i) => i.type !== "dir");
  const filtered = prefix
    ? files.filter((i) => i.path === prefix || i.path.startsWith(prefix + "/"))
    : files;
  return filtered
    .map((i) => ({
      path: i.path,
      name: i.path.split("/").pop() || i.path,
      type: i.type,
      size: i.size,
    }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

export function taskIdsFromFiles(items: FileItem[]): string[] {
  const ids = new Set<string>();
  for (const item of items) {
    const m = item.path.match(/^tasks\/([^/]+)/);
    if (m?.[1]) ids.add(m[1]);
  }
  return Array.from(ids).sort();
}

/** True when package digest listing includes Dataset-level shared/ (#65). */
export function hasSharedFiles(items: FileItem[]): boolean {
  return items.some(
    (i) => i.path === "shared" || i.path.startsWith("shared/"),
  );
}

/** Total byte size of file entries under shared/ (dirs size 0). */
export function sharedFilesStats(items: FileItem[]): {
  fileCount: number;
  totalBytes: number;
} {
  let fileCount = 0;
  let totalBytes = 0;
  for (const i of items) {
    if (i.type === "dir") continue;
    if (i.path === "shared" || i.path.startsWith("shared/")) {
      fileCount += 1;
      totalBytes += i.size || 0;
    }
  }
  return { fileCount, totalBytes };
}

/**
 * Suite rows store the local plugin.yaml id (`nooa`). Marketplace routes use
 * the Registry package id (`my-lab/nooa`). Map when a catalog is available.
 */
export function resolveMarketplacePluginId(
  pluginId: string,
  catalog: PackageRelease[],
  preferredOrgId?: string | null,
): string {
  const id = pluginId.trim();
  if (!id) return id;
  if (catalog.some((p) => p.dataset_id === id)) return id;

  const previewHits = catalog.filter((p) => p.plugin_preview?.plugin_id === id);
  const suffixHits = catalog.filter((p) => {
    const db = p.dataset_id;
    return db === id || db.endsWith(`/${id}`);
  });

  const pick = (rows: PackageRelease[]): PackageRelease | undefined => {
    if (!rows.length) return undefined;
    if (preferredOrgId) {
      const org = preferredOrgId;
      const hit = rows.find(
        (p) => p.org_id === org || p.dataset_id.startsWith(`${org}/`),
      );
      if (hit) return hit;
    }
    return rows[0];
  };

  return (
    pick(previewHits)?.dataset_id ?? pick(suffixHits)?.dataset_id ?? id
  );
}

/** Marketplace plugins for a suite row (stored list, else executor inference). */
export function pluginsUsedBySuite(
  suite: SuiteRow,
  catalog: PackageRelease[] = [],
  preferredOrgId?: string | null,
): SuitePluginRef[] {
  const stored = Array.isArray(suite.plugins) ? suite.plugins : [];
  const fromStore: SuitePluginRef[] = [];
  const seen = new Set<string>();
  for (const raw of stored) {
    const id = String(raw?.plugin_id || "").trim();
    const key = id.toLowerCase();
    if (!id || seen.has(key) || BUILTIN_EXECUTOR_KINDS.has(key) || key === "default") {
      continue;
    }
    seen.add(key);
    const marketplaceId = resolveMarketplacePluginId(
      id,
      catalog,
      preferredOrgId,
    );
    const version = String(raw.version || "").trim();
    fromStore.push(
      version
        ? { plugin_id: marketplaceId, version }
        : { plugin_id: marketplaceId },
    );
  }
  const profiles = overlayAgentProfiles(suite.job_overlay);
  for (const raw of Object.values(profiles)) {
    const rows = raw?.extensions;
    if (!Array.isArray(rows)) continue;
    for (const row of rows) {
      const id = String(row?.plugin || "").trim();
      const key = id.toLowerCase();
      if (!id || seen.has(key) || BUILTIN_EXECUTOR_KINDS.has(key) || key === "default") {
        continue;
      }
      seen.add(key);
      fromStore.push({
        plugin_id: resolveMarketplacePluginId(id, catalog, preferredOrgId),
      });
    }
  }
  if (fromStore.length) return fromStore;
  if (!Object.keys(profiles).length) return [];
  for (const raw of Object.values(profiles)) {
    const exec = String(raw?.executor || "").trim();
    const key = exec.toLowerCase();
    if (!exec || seen.has(key) || BUILTIN_EXECUTOR_KINDS.has(key) || key === "default") {
      continue;
    }
    seen.add(key);
    fromStore.push({
      plugin_id: resolveMarketplacePluginId(exec, catalog, preferredOrgId),
    });
  }
  return fromStore;
}

export function decodeFileContent(file: FileContent): string {
  if (file.encoding === "base64") {
    try {
      const bin = atob(file.content);
      const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
      return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    } catch {
      return "[binary content]";
    }
  }
  return file.content;
}
