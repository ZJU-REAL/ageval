import type { JobOverlay } from "./api";
import { resolveHarnessId } from "@ageval/shared/lib/utils";

export const ATTACH_ROLE_ALL = "all";

export type OverlayRole = {
  id: string;
  harness: string;
};

/** Overlay roles in document order. */
export function overlayRoles(overlay: JobOverlay | null | undefined): OverlayRole[] {
  const profiles = overlay?.agent_profiles;
  if (!profiles || typeof profiles !== "object") return [];
  const out: OverlayRole[] = [];
  for (const [id, raw] of Object.entries(profiles)) {
    const role = id.trim();
    if (!role) continue;
    out.push({ id: role, harness: resolveHarnessId(raw) });
  }
  return out;
}

export function rolesShareHarness(roles: OverlayRole[]): boolean {
  if (roles.length < 2) return false;
  const keys = roles.map((row) => row.harness.trim().toLowerCase());
  if (keys.some((key) => !key)) return false;
  return new Set(keys).size === 1;
}

export function defaultAttachChoice(
  roles: OverlayRole[],
  agentForHarness: (harness: string) => string,
): { role: string; agent: string } {
  if (rolesShareHarness(roles)) {
    const harness = roles[0]?.harness || "";
    return { role: ATTACH_ROLE_ALL, agent: agentForHarness(harness) };
  }
  for (const row of roles) {
    const agent = agentForHarness(row.harness);
    if (agent) return { role: row.id, agent };
  }
  return { role: roles[0]?.id || ATTACH_ROLE_ALL, agent: "" };
}

/** Strip an optional `role=` prefix so the Select owns the role. */
export function attachSpecBody(spec: string): string {
  const text = spec.trim();
  if (!text) return "";
  const eq = text.indexOf("=");
  if (eq > 0 && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(text.slice(0, eq).trim())) {
    return text.slice(eq + 1).trim();
  }
  return text;
}

export function composeAttachSpec(role: string, spec: string): string {
  const body = attachSpecBody(spec);
  if (!body) return "";
  if (!role || role === ATTACH_ROLE_ALL) return body;
  return `${role}=${body}`;
}

/** Overlay invoke ids for the roles Share will stamp. */
export function overlayModelsForAttach(
  overlay: JobOverlay | null | undefined,
  role: string,
): string[] {
  const profiles = overlay?.agent_profiles;
  if (!profiles || typeof profiles !== "object") return [];
  const want = role.trim();
  const out: string[] = [];
  const seen = new Set<string>();
  for (const [id, raw] of Object.entries(profiles)) {
    if (want && want !== ATTACH_ROLE_ALL && id.trim() !== want) continue;
    const model = typeof raw?.model === "string" ? raw.model.trim() : "";
    if (!model || seen.has(model)) continue;
    seen.add(model);
    out.push(model);
  }
  return out;
}
