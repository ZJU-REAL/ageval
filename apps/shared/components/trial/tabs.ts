export type TabId =
  | "trajectory"
  | "agent"
  | "verifier"
  | "artifacts"
  | "lock"
  | "runtime";

export const TAB_LABELS: Record<TabId, string> = {
  trajectory: "Trajectory",
  agent: "Agent",
  verifier: "Verifier",
  artifacts: "Artifacts",
  lock: "Lock",
  // effects / cleanup / summary / agent.json / harness.json — not “log files”
  runtime: "Runtime",
};

export const TREE_SCOPES: Partial<Record<TabId, string>> = {
  agent: "agent",
  verifier: "verifier",
  artifacts: "artifacts",
  lock: "lock",
  runtime: "runtime",
};

export const TAB_ORDER: TabId[] = [
  "trajectory",
  "agent",
  "verifier",
  "artifacts",
  "lock",
  "runtime",
];

/** Preferred first-tab order when opening a trial. */
export const FIRST_TAB_ORDER: TabId[] = [
  "trajectory",
  "agent",
  "verifier",
  "lock",
  "runtime",
  "artifacts",
];

export function normalizeTabId(raw: string): string {
  return raw === "log" ? "runtime" : raw;
}
